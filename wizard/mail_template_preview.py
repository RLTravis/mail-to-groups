# © 2024 Erre Elle Net s.r.l. (<https://erre-elle.net>)
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class MailTemplatePreview(models.TransientModel):
    _inherit = 'mail.template.preview'
    email_to_groups = fields.Many2many(
        string='To (Groups)',
        compute='_compute_mail_template_fields',
        comodel_name='res.groups'
    )

    def _set_mail_attributes(self, values=None):
        for field in (self._MAIL_TEMPLATE_FIELDS + ['email_to_groups', ]):
            self[field] = values.get(field, False) if values else self.mail_template_id[field]

        self.partner_ids = values.get('partner_ids', False) if values else False
