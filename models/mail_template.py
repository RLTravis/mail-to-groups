# © 2024 Erre Elle Net s.r.l. (<https://erre-elle.net>)
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import fields, models, tools, Command


class MailTemplate(models.Model):
    _inherit = 'mail.template'
    email_to_groups = fields.Many2many(
        string='To (Groups)',
        comodel_name='res.groups',
        relation='email_template_groups_rel',
        column1='email_template_id',
        column2='group_id'
    )

    def generate_recipients(self, results, res_ids):
        """
        Generates the recipients of the template. Default values can ben generated
        instead of the template values if requested by template or context.
        Emails (email_to, email_cc) can be transformed into partners if requested
        in the context.
        """

        self.ensure_one()

        if self.use_default_to or self._context.get('tpl_force_default_to'):
            records = self.env[self.model].browse(res_ids).sudo()
            default_recipients = records._message_get_default_recipients()

            for res_id, recipients in default_recipients.items():
                results[res_id].pop('partner_to', None)
                results[res_id].update(recipients)

        records_company = None

        if self._context.get('tpl_partners_only') and self.model and results and 'company_id' in self.env[self.model]._fields:
            records = self.env[self.model].browse(results.keys()).read(['company_id'])
            records_company = {rec['id']: (rec['company_id'][0] if rec['company_id'] else None)
                               for rec in records}

        for res_id, values in results.items():
            partner_ids = values.get('partner_ids', [])
            results[res_id]['email_to'] = ','.join(
                list(
                    set(tools.email_split(values.get('email_to', ''))).union(
                        [user.email
                         for user in self.email_to_groups.users]
                    )
                )
            )
            values['email_to'] = ','.join(
                list(
                    set(tools.email_split(values.get('email_to', ''))).union(
                        [user.email
                         for user in self.email_to_groups.users]
                    )
                )
            )

            if self._context.get('tpl_partners_only'):
                mails = tools.email_split(values.pop('email_to', ''))
                mails += tools.email_split(values.pop('email_cc', ''))
                mails = list(set(mails))

                Partner = self.env['res.partner']

                if records_company:
                    Partner = Partner.with_context(default_company_id=records_company[res_id])

                for mail in mails:
                    partner = Partner.find_or_create(mail)
                    partner_ids.append(partner.id)

            partner_ids = list(set(partner_ids))
            partner_to = values.pop('partner_to', '')

            if partner_to:
                # placeholders could generate '', 3, 2 due to some empty field values
                tpl_partner_ids = [int(pid.strip())
                                   for pid in partner_to.split(',')
                                   if (pid and pid.strip().isdigit())]
                partner_ids += self.env['res.partner'].sudo().browse(tpl_partner_ids).exists().ids

            results[res_id]['partner_ids'] = partner_ids

        return results

    def generate_email(self, res_ids, fields):
        """
        Generates an email from the template for given the given model based on
        records given by res_ids.

        :param res_id: id of the record to use for rendering the template (model
                       is taken from template definition)
        :returns: a dict containing all relevant fields for creating a new
                  mail.mail entry, with one extra key ``attachments``, in the
                  format [(report_name, data)] where data is base64 encoded.
        """

        res = super().generate_email(res_ids, fields)
        res.update(
            {
                'email_to_groups': self.email_to_groups,
            }
        )
        return res

    def send_mail(
        self,
        res_id,
        force_send=False,
        raise_exception=False,
        email_values=None,
        email_layout_xmlid=False
    ):
        """
        Generates a new mail.mail. Template is rendered on record given by
        res_id and model coming from template.

        :param int res_id: id of the record to render the template
        :param bool force_send: send email immediately; otherwise use the mail
            queue (recommended);
        :param dict email_values: update generated mail with those values to further
            customize the mail;
        :param str email_layout_xmlid: optional notification layout to encapsulate the
            generated email;
        :returns: id of the mail.mail that was created
        """

        # Grant access to send_mail only if access to related document
        self.ensure_one()
        self._send_check_access([res_id])

        Attachment = self.env['ir.attachment']  # TDE FIXME: should remove default_type from context

        # create a mail_mail based on values, without attachments
        values = self.generate_email(
            res_id,
            [
                'subject',
                'body_html',
                'email_from',
                'email_cc',
                'email_to',
                'partner_to',
                'reply_to',
                'auto_delete',
                'scheduled_date',
            ]
        )
        values['recipient_ids'] = [Command.link(pid)
                                   for pid in values.get('partner_ids', [])]
        values['attachment_ids'] = [Command.link(aid)
                                    for aid in values.get('attachment_ids', [])]
        values.update(email_values or {})
        attachment_ids = values.pop('attachment_ids', [])
        attachments = values.pop('attachments', [])

        # add a protection against void email_from
        if 'email_from' in values and not values.get('email_from'):
            values.pop('email_from')

        # encapsulate body
        if email_layout_xmlid and values['body_html']:
            record = self.env[self.model].browse(res_id)
            model = self.env['ir.model']._get(record._name)

            if self.lang:
                lang = self._render_lang([res_id])[res_id]
                model = model.with_context(lang=lang)

            values['body_html'] = self.env['mail.render.mixin']._replace_local_links(
                model.env['ir.qweb']._render(
                    email_layout_xmlid,
                    {
                        # message
                        'message': self.env['mail.message'].sudo().new(
                            {
                                'body': values['body_html'],
                                'record_name': record.display_name,
                            }
                        ),
                        'subtype': self.env['mail.message.subtype'].sudo(),
                        # record
                        'model_description': model.display_name,
                        'record': record,
                        'record_name': False,
                        'subtitles': False,
                        # user / environment
                        'company': 'company_id' in record and record['company_id'] or self.env.company,
                        'email_add_signature': False,
                        'signature': '',
                        'website_url': '',
                        # tools
                        'is_html_empty': tools.is_html_empty,
                    },
                    minimal_qcontext=True,
                    raise_if_not_found=False
                )
            )

        del values['email_to_groups']

        mail = self.env['mail.mail'].sudo().create(values)

        # manage attachments
        for attachment in attachments:
            attachment_ids.append(
                (
                    4,
                    Attachment.create(
                        {
                            'name': attachment[0],
                            'datas': attachment[1],
                            'type': 'binary',
                            'res_model': 'mail.message',
                            'res_id': mail.mail_message_id.id,
                        }
                    ).id,
                )
            )

        if attachment_ids:
            mail.write(
                {
                    'attachment_ids': attachment_ids,
                }
            )

        if force_send:
            mail.send(raise_exception=raise_exception)

        return mail.id  # TDE CLEANME: return mail + api.returns ?
