from odoo import models, fields


class MigrationDiagnosticVolume(models.Model):
    _name = 'migration.diagnostic.volume'
    _description = 'Analyzed data volume'
    _order = 'phase, migration_priority'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    model_name = fields.Char(string='Odoo model', required=True)
    label = fields.Char(string='Label')
    phase = fields.Selection([
        ('1', 'Phase 1 — Reference data'),
        ('2', 'Phase 2 — Business data'),
    ], string='Migration phase')
    migration_priority = fields.Integer(string='Migration order')
    record_count = fields.Integer(string='Number of records')
    volume_level = fields.Selection([
        ('none',     'Empty'),
        ('low',      'Low (< 1,000)'),
        ('medium',   'Medium (1k – 10k)'),
        ('high',     'High (10k – 100k)'),
        ('critical', 'Critical (> 100k)'),
    ], string='Volume level')
    available = fields.Boolean(string='Model available', default=True)
    volume_color = fields.Integer(compute='_compute_volume_color')

    def _compute_volume_color(self):
        colors = {'none': 0, 'low': 10, 'medium': 3, 'high': 2, 'critical': 1}
        for rec in self:
            rec.volume_color = colors.get(rec.volume_level, 0)
