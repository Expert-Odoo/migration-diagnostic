from odoo import models, fields, api, _


class MigrationScanWizard(models.TransientModel):
    _name = 'migration.scan.wizard'
    _description = 'Migration Diagnostic Wizard'

    name = fields.Char(
        string='Report Name',
        default=lambda self: _('Migration diagnostic — ') + fields.Date.today().strftime('%Y-%m-%d'),
        required=True,
    )
    include_messages = fields.Boolean(
        string='Include mail.message count',
        default=True,
        help='Counting messages can be slow on large databases.',
    )
    include_attachments = fields.Boolean(
        string='Include ir.attachment count',
        default=True,
    )
    info = fields.Html(
        string='Information',
        default=lambda self: _("""
        <div class="alert alert-info">
            <b>🔍 What the scan analyzes:</b><br/>
            <ul>
                <li>Complete inventory of installed modules (standard / OCA / custom)</li>
                <li>Volume of critical data (partners, invoices, orders...)</li>
                <li>Detection of risk factors (multi-company, custom fields, Python actions...)</li>
                <li>Overall complexity score and effort estimate</li>
                <li>Recommendations by migration phase</li>
            </ul>
            <b>⏱ Estimated duration:</b> 10 to 60 seconds depending on database size.
        </div>
        """),
    )

    def action_launch_scan(self):
        diagnostic = self.env['migration.diagnostic'].create({'name': self.name})
        diagnostic.action_run_scan(
            include_messages=self.include_messages,
            include_attachments=self.include_attachments,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnostic Result'),
            'res_model': 'migration.diagnostic',
            'res_id': diagnostic.id,
            'view_mode': 'form',
            'target': 'current',
        }
