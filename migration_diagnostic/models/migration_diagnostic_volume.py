from odoo import models, fields


class MigrationDiagnosticVolume(models.Model):
    _name = 'migration.diagnostic.volume'
    _description = 'Volume de données analysé'
    _order = 'phase, migration_priority'

    diagnostic_id = fields.Many2one('migration.diagnostic', ondelete='cascade', required=True)
    model_name = fields.Char(string='Modèle Odoo', required=True)
    label = fields.Char(string='Libellé')
    phase = fields.Selection([
        ('1', 'Phase 1 — Socle référentiel'),
        ('2', 'Phase 2 — Données métier'),
    ], string='Phase de migration')
    migration_priority = fields.Integer(string='Ordre de migration')
    record_count = fields.Integer(string='Nombre d\'enregistrements')
    volume_level = fields.Selection([
        ('none',     'Vide'),
        ('low',      'Faible (< 1 000)'),
        ('medium',   'Moyen (1k – 10k)'),
        ('high',     'Élevé (10k – 100k)'),
        ('critical', 'Critique (> 100k)'),
    ], string='Niveau de volume')
    available = fields.Boolean(string='Modèle disponible', default=True)
    volume_color = fields.Integer(compute='_compute_volume_color')

    def _compute_volume_color(self):
        colors = {'none': 0, 'low': 10, 'medium': 3, 'high': 2, 'critical': 1}
        for rec in self:
            rec.volume_color = colors.get(rec.volume_level, 0)
