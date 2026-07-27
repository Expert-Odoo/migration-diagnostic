from odoo import models, fields


class MigrationDiagnosticRisk(models.Model):
    _name = 'migration.diagnostic.risk'
    _description = 'Facteur de risque de migration'
    _order = 'risk_level desc, name'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Facteur de risque', required=True)
    description = fields.Text(string='Détail')
    risk_level = fields.Selection([
        ('low',    'Faible ✅'),
        ('medium', 'Moyen ⚠️'),
        ('high',   'Élevé 🔴'),
    ], string='Niveau de risque', required=True)
    recommendation = fields.Text(string='Recommandation')
    risk_color = fields.Integer(compute='_compute_risk_color')

    def _compute_risk_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2}
        for rec in self:
            rec.risk_color = colors.get(rec.risk_level, 0)
