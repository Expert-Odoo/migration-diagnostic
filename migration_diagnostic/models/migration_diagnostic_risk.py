from odoo import models, fields


class MigrationDiagnosticRisk(models.Model):
    _name = 'migration.diagnostic.risk'
    _description = 'Migration Risk Factor'
    _order = 'risk_level desc, name'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    code = fields.Char(string='Code', required=True)
    name = fields.Char(string='Risk Factor', required=True)
    description = fields.Text(string='Details')
    risk_level = fields.Selection([
        ('low',    'Low ✅'),
        ('medium', 'Medium ⚠️'),
        ('high',   'High 🔴'),
    ], string='Risk Level', required=True)
    recommendation = fields.Text(string='Recommendation')
    risk_color = fields.Integer(compute='_compute_risk_color')

    def _compute_risk_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2}
        for rec in self:
            rec.risk_color = colors.get(rec.risk_level, 0)
