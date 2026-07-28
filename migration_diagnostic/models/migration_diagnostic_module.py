from odoo import models, fields


class MigrationDiagnosticModule(models.Model):
    _name = 'migration.diagnostic.module'
    _description = 'Module Odoo analysé'
    _order = 'category, name'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    name = fields.Char(string='Nom', required=True)
    technical_name = fields.Char(string='Nom technique')
    shortdesc = fields.Char(string='Description')
    author = fields.Char(string='Auteur')
    installed_version = fields.Char(string='Version installée')
    latest_version = fields.Char(string='Dernière version')
    category = fields.Selection([
        ('standard', 'Standard Odoo'),
        ('oca',      'OCA'),
        ('custom',   'Custom / Tiers'),
    ], string='Catégorie', required=True)
    risk_level = fields.Selection([
        ('low',    'Faible'),
        ('medium', 'Moyen'),
        ('high',   'Élevé'),
    ], string='Risque migration')
    risk_color = fields.Integer(compute='_compute_risk_color')
    notes = fields.Text(string='Notes')

    def _compute_risk_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2}
        for rec in self:
            rec.risk_color = colors.get(rec.risk_level, 0)
