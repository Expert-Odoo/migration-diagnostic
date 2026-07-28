from odoo import models, fields


class MigrationDiagnosticModule(models.Model):
    _name = 'migration.diagnostic.module'
    _description = 'Analyzed Odoo module'
    _order = 'category, name'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    name = fields.Char(string='Name', required=True)
    technical_name = fields.Char(string='Technical name')
    shortdesc = fields.Char(string='Description')
    author = fields.Char(string='Author')
    installed_version = fields.Char(string='Installed version')
    latest_version = fields.Char(string='Latest version')
    category = fields.Selection([
        ('standard', 'Standard Odoo'),
        ('oca',      'OCA'),
        ('custom',   'Custom / third-party'),
    ], string='Category', required=True)
    risk_level = fields.Selection([
        ('low',    'Low'),
        ('medium', 'Medium'),
        ('high',   'High'),
    ], string='Migration risk')
    risk_color = fields.Integer(compute='_compute_risk_color')
    notes = fields.Text(string='Notes')

    def _compute_risk_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2}
        for rec in self:
            rec.risk_color = colors.get(rec.risk_level, 0)
