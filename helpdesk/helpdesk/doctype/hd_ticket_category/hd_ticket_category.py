# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

# import frappe
#from frappe.utils.nestedset import NestedSet


#class HDTicketCategory(NestedSet):
#	pass
import frappe
from frappe.utils.nestedset import NestedSet

class HDTicketCategory(NestedSet):
    nsm_parent_field = "parent_hd_ticket_category"

    def autoname(self):
        if self.parent_hd_ticket_category:
            self.name = f"{self.parent_hd_ticket_category} - {self.category_name}"
        else:
            self.name = self.category_name

    def on_update(self):
        super().on_update()
