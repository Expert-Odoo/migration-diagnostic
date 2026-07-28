from odoo import models, fields, api, _


class MigrationScanWizard(models.TransientModel):
    _name = 'migration.scan.wizard'
    _description = 'Migration diagnostic wizard'

    name = fields.Char(
        string='Report name',
        default=lambda self: _('Migration diagnostic — %s') % fields.Date.today().strftime('%d/%m/%Y'),
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
                <li>Full inventory of installed modules (standard / OCA / custom)</li>
                <li>Volume of critical data (partners, invoices, orders...)</li>
                <li>Risk factor detection (multi-company, custom fields, Python actions...)</li>
                <li>Global complexity score and effort estimate</li>
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
            'name': _('Diagnostic result'),
            'res_model': 'migration.diagnostic',
            'res_id': diagnostic.id,
            'view_mode': 'form',
            'target': 'current',
        }
