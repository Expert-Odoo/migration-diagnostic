from odoo import models, fields, api, _


class MigrationScanWizard(models.TransientModel):
    _name = 'migration.scan.wizard'
    _description = 'Assistant de diagnostic de migration'

    name = fields.Char(
        string='Nom du rapport',
        default=lambda self: _('Diagnostic migration — ') + fields.Date.today().strftime('%d/%m/%Y'),
        required=True,
    )
    include_messages = fields.Boolean(
        string='Inclure le comptage mail.message',
        default=True,
        help='Le comptage des messages peut être long sur les grandes bases.',
    )
    include_attachments = fields.Boolean(
        string='Inclure le comptage ir.attachment',
        default=True,
    )
    info = fields.Html(
        string='Information',
        default="""
        <div class="alert alert-info">
            <b>🔍 Ce que le scan analyse :</b><br/>
            <ul>
                <li>Inventaire complet des modules installés (standard / OCA / custom)</li>
                <li>Volumétrie des données critiques (partenaires, factures, commandes...)</li>
                <li>Détection des facteurs de risque (multi-société, champs custom, actions Python...)</li>
                <li>Score de complexité globale et estimation de charge</li>
                <li>Recommandations par phase de migration</li>
            </ul>
            <b>⏱ Durée estimée :</b> 10 à 60 secondes selon la taille de la base.
        </div>
        """,
    )

    def action_launch_scan(self):
        diagnostic = self.env['migration.diagnostic'].create({'name': self.name})
        diagnostic.action_run_scan(
            include_messages=self.include_messages,
            include_attachments=self.include_attachments,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Résultat du diagnostic'),
            'res_model': 'migration.diagnostic',
            'res_id': diagnostic.id,
            'view_mode': 'form',
            'target': 'current',
        }
