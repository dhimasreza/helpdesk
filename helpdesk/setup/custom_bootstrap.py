kimport frappe
from textwrap import dedent


def create_server_script(
    name,
    script_type,
    script,
    reference_doctype=None,
    doctype_event=None,
    api_method=None,
    allow_guest=0,
):
    if frappe.db.exists("Server Script", name):
        return

    frappe.get_doc({
        "doctype": "Server Script",
        "name": name,
        "script_type": script_type,
        "reference_doctype": reference_doctype,
        "doctype_event": doctype_event,
        "api_method": api_method,
        "allow_guest": allow_guest,
        "script": script.strip(),
        "disabled": 0
    }).insert(ignore_permissions=True)


def create_server_scripts():

    # 1. Generate tracking token
    create_server_script(
        name="Auto-generate token saat ticket dibuat",
        script_type="DocType Event",
        reference_doctype="HD Ticket",
        doctype_event="Before Insert",
        script="""\
if not doc.tracking_token:
    doc.tracking_token = frappe.utils.generate_hash(length=24)
    doc.tracking_token_expiry = frappe.utils.add_to_date(
        frappe.utils.now_datetime(),
        years=1
    )
"""
    )

    # 2. Public API
    create_server_script(
        name="Public api ticket tracking",
        script_type="API",
        api_method="ticket",
        allow_guest=1,
        script="""\
token = frappe.request.args.get("token", "").strip()

if not token:
    frappe.response["http_status_code"] = 400
    frappe.response["message"] = {"error": "Token required"}

elif len(token) < 20:
    frappe.response["http_status_code"] = 400
    frappe.response["message"] = {"error": "Invalid token"}

else:
    ticket = frappe.get_all(
        "HD Ticket",
        filters={"tracking_token": token},
        fields=[
            "name", "subject", "status", "description",
            "creation", "modified", "priority",
            "resolution_details", "resolution_date"
        ],
        limit=1
    )

    if not ticket:
        frappe.response["http_status_code"] = 404
        frappe.response["message"] = {"error": "Ticket not found"}

    else:
        t = ticket[0]
        expiry = frappe.db.get_value("HD Ticket", t["name"], "tracking_token_expiry")

        if expiry and frappe.utils.get_datetime(expiry) < frappe.utils.now_datetime():
            frappe.response["http_status_code"] = 410
            frappe.response["message"] = {"error": "Tracking token expired"}

        else:
            assigned = frappe.get_all(
                "ToDo",
                filters={
                    "reference_type": "HD Ticket",
                    "reference_name": t["name"],
                    "status": "Open"
                },
                fields=["owner"],
                limit=1
            )

            agent_name = None
            if assigned:
                agent_name = frappe.db.get_value(
                    "User", assigned[0]["owner"], "full_name"
                )

            timeline = [{
                "type": "created",
                "label": "Ticket Opened",
                "time": str(t["creation"]),
                "agent": "System"
            }]

            logs = frappe.get_all(
                "HD Ticket Status Log",
                filters={"ticket": t["name"]},
                fields=["status", "changed_at", "changed_by"],
                order_by="changed_at asc"
            )

            status_map = {
                "In Progress": "progress",
                "Resolved": "resolved",
                "Closed": "closed"
            }

            for log in logs:
                if log.status in status_map:
                    agent = "System"
                    if log.changed_by:
                        agent = frappe.db.get_value(
                            "User", log.changed_by, "full_name"
                        ) or "System"

                    timeline.append({
                        "type": status_map[log.status],
                        "label": log.status,
                        "time": str(log.changed_at),
                        "agent": agent
                    })

            frappe.response["message"] = {
                **t,
                "assigned_agent": agent_name,
                "timeline": timeline
            }
"""
    )

    # 3. Log status changes
    create_server_script(
        name="Catat perubahan status setelah ticket ada",
        script_type="DocType Event",
        reference_doctype="HD Ticket",
        doctype_event="Before Save",
        script="""\
if not doc.is_new() and doc.has_value_changed("status"):
    user = frappe.session.user

    if user in ["Administrator", "Guest"]:
        assigned = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "HD Ticket",
                "reference_name": doc.name,
                "status": "Open"
            },
            fields=["owner"],
            limit=1
        )
        if assigned:
            user = assigned[0]["owner"]

    frappe.get_doc({
        "doctype": "HD Ticket Status Log",
        "ticket": doc.name,
        "status": doc.status,
        "changed_at": frappe.utils.now_datetime(),
        "changed_by": user
    }).insert(ignore_permissions=True)
"""
    )

    # 4. First status log
    create_server_script(
        name="Catat status saat ticket pertama dibuat",
        script_type="DocType Event",
        reference_doctype="HD Ticket",
        doctype_event="After Insert",
        script="""\
frappe.get_doc({
    "doctype": "HD Ticket Status Log",
    "ticket": doc.name,
    "status": doc.status,
    "changed_at": frappe.utils.now_datetime(),
    "changed_by": None
}).insert(ignore_permissions=True)
"""
    )


def create_client_script():
    if frappe.db.exists("Client Script", "Custom Tree Picker di HD Ticket Form"):
        return

    frappe.get_doc({
        "doctype": "Client Script",
        "name": "Custom Tree Picker di HD Ticket Form",
        "dt": "HD Ticket",
        "enabled": 1,
        "script": """\
frappe.ui.form.on("HD Ticket", {
    refresh(frm) {
        let field = frm.fields_dict["ticket_category"];
        if (!field) return;
        field.$input.off("click").on("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            let tree_dialog = new frappe.ui.Dialog({
                title: __("Select Ticket Category"),
                size: "large"
            });
            tree_dialog.show();
            setTimeout(() => {
                frappe.call({
                    method: "frappe.desk.treeview.get_children",
                    args: {
                        doctype: "HD Ticket Category",
                        parent: "",
                        is_tree: 1,
                    },
                    callback(r) {
                        if (!r.message) return;
                        let $tree = $(`<ul class="tree"></ul>`).appendTo(tree_dialog.body);
                        function renderNodes(nodes, $parent) {
                            nodes.forEach(node => {
                                let $li = $(`
                                    <li class="tree-node" style="padding: 2px 0;">
                                        <span class="tree-link"
                                            data-label="${node.value}"
                                            data-expandable="${node.expandable ? 1 : 0}"
                                            style="cursor:pointer; padding: 3px 8px; display:block; font-size:12px; color:var(--text-color); border-radius:4px;">
                                            ${node.expandable ? "\\uD83D\\uDCC1" : "\\u25CB"} ${node.value}
                                        </span>
                                        <ul class="children" style="list-style:none; padding-left:16px; display:none; margin:0;"></ul>
                                    </li>
                                `).appendTo($parent);
                                $li.find("> .tree-link")
                                    .on("mouseenter", function () { $(this).css("background", "var(--fg-color)"); })
                                    .on("mouseleave", function () { $(this).css("background", ""); })
                                    .on("click", function () {
                                        let $children = $li.find("> .children");
                                        if (node.expandable) {
                                            if ($children.is(":visible")) {
                                                $children.hide();
                                                return;
                                            }
                                            frappe.call({
                                                method: "frappe.desk.treeview.get_children",
                                                args: {
                                                    doctype: "HD Ticket Category",
                                                    parent: node.value,
                                                    is_tree: 1,
                                                },
                                                callback(r2) {
                                                    $children.empty();
                                                    renderNodes(r2.message || [], $children);
                                                    $children.show();
                                                }
                                            });
                                        } else {
                                            frm.set_value("ticket_category", node.value);
                                            tree_dialog.hide();
                                        }
                                    });
                            });
                        }
                        renderNodes(r.message, $tree);
                    }
                });
            }, 200);
        });
    }
});
"""
    }).insert(ignore_permissions=True)


def create_web_page():
    html = """\
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>

<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f2f5;font-family:'Inter',sans-serif;min-height:100vh;padding:24px 16px}
.wrap{max-width:640px;margin:0 auto}
.header{margin-bottom:20px}
.header h2{font-size:20px;font-weight:600;color:#111;display:flex;align-items:center;gap:8px}
.header h2 svg{width:20px;height:20px;stroke:#3b82f6;fill:none;stroke-width:2}
.header p{font-size:13px;color:#666;margin-top:4px;margin-left:28px}
.search-card{background:#fff;border-radius:14px;border:1px solid #e5e7eb;padding:16px;margin-bottom:16px;display:flex;gap:8px}
.search-card input{flex:1;padding:10px 14px;border-radius:10px;border:1px solid #e5e7eb;background:#f9fafb;color:#111;font-size:13px;font-family:inherit;outline:none;transition:border 0.15s,box-shadow 0.15s}
.search-card input:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,0.1);background:#fff}
.search-card button{padding:10px 20px;border-radius:10px;border:none;background:#3b82f6;color:#fff;font-size:13px;font-weight:500;font-family:inherit;cursor:pointer;transition:background 0.15s}
.search-card button:hover{background:#2563eb}
.error-msg{font-size:13px;color:#dc2626;margin-bottom:12px;padding:10px 14px;border-radius:10px;border:1px solid #fca5a5;background:#fff1f1;display:none}
.loading{font-size:13px;color:#555;margin-bottom:12px;padding:10px 14px;display:none}
.card{background:#fff;border-radius:16px;border:1px solid #e5e7eb;overflow:hidden;display:none;box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.card-head{padding:20px 24px 16px;border-bottom:1px solid #ebebeb;background:#fff}
.card-head-strip{height:4px;border-radius:4px;margin-bottom:16px}
.title-row{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}
.ticket-subject{font-size:16px;font-weight:600;color:#111;line-height:1.4}
.badge{display:inline-flex;align-items:center;padding:4px 12px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:0.02em;white-space:nowrap;flex-shrink:0}
.badge.open{background:#fef9c3;color:#854d0e;border:1px solid #fde68a}
.badge.progress{background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe}
.badge.replied{background:#ede9fe;color:#5b21b6;border:1px solid #ddd6fe}
.badge.resolved{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}
.badge.closed{background:#f3f4f6;color:#374151;border:1px solid #d1d5db}
.ticket-meta{display:flex;gap:4px;flex-wrap:wrap;align-items:center}
.meta-chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#444;padding:3px 8px;background:#f5f5f5;border-radius:6px;border:1px solid #e5e5e5}
.meta-chip strong{color:#111;font-weight:600}
.card-body{padding:0}
.section{padding:16px 24px;border-bottom:1px solid #f0f0f0}
.section:last-child{border-bottom:none}
.section-label{font-size:11px;font-weight:700;color:#555;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px}
.section-label-row{display:flex;align-items:center;gap:6px;margin-bottom:12px}
.section-label-row .section-label{margin-bottom:0}
.section-label-icon{width:14px;height:14px;stroke:#10b981;fill:none;stroke-width:2.5;flex-shrink:0}
.agent-row{display:flex;align-items:center;gap:12px;padding:12px;background:#f9fafb;border-radius:10px;border:1px solid #e5e7eb}
.avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#6366f1);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:#fff;flex-shrink:0}
.agent-name{font-size:14px;font-weight:600;color:#111}
.agent-role{font-size:12px;color:#555;margin-top:1px}
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.info-cell{background:#f9fafb;border-radius:10px;padding:12px 14px;border:1px solid #e5e7eb}
.ic-label{font-size:11px;color:#555;font-weight:500;margin-bottom:4px}
.ic-val{font-size:14px;color:#111;font-weight:600}
.desc-box{font-size:13px;color:#333;line-height:1.7;padding:12px 14px;background:#f9fafb;border-radius:10px;border:1px solid #e5e7eb;border-left:3px solid #3b82f6}
.resolution-box{font-size:13px;color:#14532d;line-height:1.7;padding:14px 16px;background:#f0fdf4;border-radius:10px;border:1px solid #bbf7d0;border-left:3px solid #10b981}
.resolution-placeholder{font-size:13px;color:#666;padding:12px 14px;background:#f9fafb;border-radius:10px;border:1px dashed #d1d5db;text-align:center}
.tl-item{display:flex;gap:12px}
.tl-left{display:flex;flex-direction:column;align-items:center;width:20px;flex-shrink:0}
.tl-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;margin-top:2px;border:2px solid #fff;box-shadow:0 0 0 2px var(--dc,#ccc)}
.tl-connector{width:2px;background:#e5e7eb;flex:1;margin:4px 0;min-height:16px}
.tl-right{flex:1;padding-bottom:16px}
.tl-item:last-child .tl-right{padding-bottom:0}
.tl-row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.tl-title{font-size:13px;font-weight:600;color:#111;line-height:1.4}
.tl-time{font-size:11px;color:#555;flex-shrink:0;margin-top:2px;font-weight:500}
.tl-agent{font-size:12px;color:#444;margin-top:2px;font-weight:500}
</style>

<h2 class="sr-only" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)">Ticket Tracking</h2>

<div class="wrap">
  <div class="header">
    <h2>
      <svg viewBox="0 0 24 24"><path d="M15 5v2M15 11v2M15 17v2M5 5h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z"/></svg>
      Ticket Tracking
    </h2>
    <p>Enter your tracking token to view real-time status</p>
  </div>

  <div class="search-card">
    <input id="token_input" placeholder="Enter tracking token..." />
    <button onclick="manualTrack()">Track</button>
  </div>

  <div id="error" class="error-msg"></div>
  <div id="loading" class="loading">Loading ticket...</div>

  <div id="card" class="card">
    <div class="card-head">
      <div id="head_strip" class="card-head-strip"></div>
      <div class="title-row">
        <div id="subject" class="ticket-subject"></div>
        <span id="status" class="badge"></span>
      </div>
      <div class="ticket-meta">
        <div class="meta-chip">ID <strong id="ticket_id"></strong></div>
        <div class="meta-chip">Created <strong id="created"></strong></div>
        <div class="meta-chip">Last Updated <strong id="updated"></strong></div>
      </div>
    </div>

    <div class="card-body">
      <div class="section">
        <div class="section-label">Assigned agent</div>
        <div class="agent-row">
          <div class="avatar" id="avatar_initials"></div>
          <div>
            <div class="agent-name" id="agent"></div>
            <div class="agent-role">Support agent</div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-label">Details</div>
        <div class="info-grid">
          <div class="info-cell"><div class="ic-label">Priority</div><div class="ic-val" id="priority">-</div></div>
          <div class="info-cell"><div class="ic-label">Status</div><div class="ic-val" id="status2">-</div></div>
        </div>
      </div>

      <div class="section">
        <div class="section-label">Description</div>
        <div id="description" class="desc-box"></div>
      </div>

      <div class="section" id="resolution_section" style="display:none">
        <div class="section-label-row">
          <svg class="section-label-icon" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <div class="section-label">Resolution</div>
        </div>
        <div id="resolution_content"></div>
      </div>

      <div class="section">
        <div class="section-label">Activity timeline</div>
        <div id="timeline"></div>
      </div>
    </div>
  </div>
</div>

<script>
const rl={r:[],max:5,win:30000,ok(){const n=Date.now();this.r=this.r.filter(t=>n-t<this.win);if(this.r.length>=this.max)return false;this.r.push(n);return true}};

const STATUS_CFG={
  "Open":{cls:"open",strip:"#f59e0b",dot:"#f59e0b"},
  "In Progress":{cls:"progress",strip:"#3b82f6",dot:"#3b82f6"},
  "Replied":{cls:"replied",strip:"#8b5cf6",dot:"#8b5cf6"},
  "Resolved":{cls:"resolved",strip:"#10b981",dot:"#10b981"},
  "Closed":{cls:"closed",strip:"#6b7280",dot:"#6b7280"}
};
const TYPE_DOT={created:"#f59e0b",progress:"#3b82f6",replied:"#8b5cf6",resolved:"#10b981",closed:"#6b7280"};

function fmt(d){if(!d)return"-";return new Date(d).toLocaleString('id-ID',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}
function esc(s){if(!s)return"-";return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function initials(n){if(!n)return"?";return n.trim().split(/\\s+/).slice(0,2).map(w=>w[0]).join("").toUpperCase()}

function renderTimeline(items=[]){
  if(!items.length)return'<div style="font-size:12px;color:#666">No activity recorded</div>';
  return items.map((i,idx)=>{
    const color=TYPE_DOT[i.type]||"#ccc";
    return'<div class="tl-item">'
      +'<div class="tl-left">'
      +'<div class="tl-dot" style="background:'+color+';--dc:'+color+'"></div>'
      +(idx!==items.length-1?'<div class="tl-connector"></div>':'')
      +'</div>'
      +'<div class="tl-right">'
      +'<div class="tl-row">'
      +'<div class="tl-title">'+esc(i.label)+'</div>'
      +'<div class="tl-time">'+fmt(i.time)+'</div>'
      +'</div>'
      +(i.agent?'<div class="tl-agent">'+esc(i.agent)+'</div>':'')
      +'</div>'
      +'</div>';
  }).join("")
}

function renderResolution(t){
  const section=document.getElementById("resolution_section");
  const content=document.getElementById("resolution_content");
  const isResolved=["Resolved","Closed"].includes(t.status);
  if(!isResolved){section.style.display="none";return}
  section.style.display="block";
  if(t.resolution_details){
    content.innerHTML='<div class="resolution-box">'+DOMPurify.sanitize(t.resolution_details)+'</div>';
  }else{
    content.innerHTML='<div class="resolution-placeholder">Ticket marked as <strong>'+esc(t.status)+'</strong> - no resolution notes provided.</div>';
  }
}

async function track(token){
  const loading=document.getElementById("loading");
  const errorDiv=document.getElementById("error");
  const card=document.getElementById("card");
  errorDiv.style.display="none";
  card.style.display="none";
  if(!rl.ok()){errorDiv.textContent="Too many requests. Please wait.";errorDiv.style.display="block";return}
  loading.style.display="block";
  try{
    const res=await fetch("/api/method/ticket?token="+encodeURIComponent(token));
    const data=await res.json();
    loading.style.display="none";
    if(!res.ok||!data.message){errorDiv.textContent=(data.message&&data.message.error)||"Ticket not found.";errorDiv.style.display="block";return}
    const t=data.message;
    const cfg=STATUS_CFG[t.status]||STATUS_CFG["Closed"];
    document.getElementById("subject").textContent=t.subject||"-";
    document.getElementById("description").innerHTML=DOMPurify.sanitize(t.description||"-");
    document.getElementById("ticket_id").textContent=t.name||"-";
    document.getElementById("agent").textContent=t.assigned_agent||"-";
    document.getElementById("avatar_initials").textContent=initials(t.assigned_agent);
    document.getElementById("head_strip").style.background=cfg.strip;
    const st=document.getElementById("status");
    st.textContent=t.status||"-";
    st.className="badge "+cfg.cls;
    document.getElementById("status2").textContent=t.status||"-";
    document.getElementById("created").textContent=fmt(t.creation);
    document.getElementById("updated").textContent=fmt(t.modified);
    document.getElementById("priority").textContent=t.priority||"-";
    document.getElementById("timeline").innerHTML=renderTimeline(t.timeline||[]);
    renderResolution(t);
    card.style.display="block";
  }catch(e){
    loading.style.display="none";
    errorDiv.textContent="Failed to load ticket. Please try again.";
    errorDiv.style.display="block";
  }
}

function manualTrack(){
  const token=document.getElementById("token_input").value.trim();
  if(!token)return;
  const url=new URL(window.location);
  url.searchParams.set("token",token);
  window.location=url.toString();
}

document.getElementById("token_input").addEventListener("keypress",function(e){if(e.key==="Enter")manualTrack()});
const params=new URLSearchParams(window.location.search);
const token=params.get("token");
if(token){document.getElementById("token_input").value=token;track(token)}
</script>
"""

    if frappe.db.exists("Web Page", {"route": "ticket-tracking"}):
        doc = frappe.get_doc("Web Page", {"route": "ticket-tracking"})
    else:
        doc = frappe.new_doc("Web Page")

    doc.title = "Ticket Tracking"
    doc.route = "ticket-tracking"
    doc.published = 1
    doc.content_type = "HTML"
    doc.dynamic_route = 0

    doc.main_section_html = html
    doc.main_section = html   # optional backup

    doc.save(ignore_permissions=True)
    frappe.db.commit()


def execute():
    create_server_scripts()
    create_client_script()
    create_web_page()
    frappe.db.commit()
