import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MigrationDiagnostic(models.Model):
    _name = 'migration.diagnostic'
    _description = 'Diagnostic de migration Odoo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Identité ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Référence',
        required=True,
        default=lambda self: _('Diagnostic du ') + fields.Datetime.now().strftime('%d/%m/%Y %H:%M'),
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('scanning', 'Analyse en cours...'),
        ('done', 'Terminé'),
        ('error', 'Erreur'),
    ], default='draft', string='État', tracking=True)

    source_version = fields.Char(string='Version Odoo source', readonly=True)
    scan_date = fields.Datetime(string='Date du scan', readonly=True)
    scan_duration = fields.Float(string='Durée du scan (s)', readonly=True)

    # ── Résultats ─────────────────────────────────────────────────────────────
    complexity_score = fields.Integer(
        string='Score de complexité',
        readonly=True,
        help='Score global de 0 à 100. Plus il est élevé, plus la migration est complexe.',
    )
    complexity_level = fields.Selection([
        ('low',      'Faible ✅'),
        ('medium',   'Moyen ⚠️'),
        ('high',     'Élevé 🔴'),
        ('critical', 'Critique 🚨'),
    ], string='Niveau de complexité', readonly=True, tracking=True)
    complexity_color = fields.Integer(compute='_compute_complexity_color')

    estimated_days_min = fields.Integer(string='Charge estimée min (j)', readonly=True)
    estimated_days_max = fields.Integer(string='Charge estimée max (j)', readonly=True)
    estimated_days_label = fields.Char(compute='_compute_estimated_days_label', string='Estimation')

    # ── Synthèse modules ──────────────────────────────────────────────────────
    module_count_total = fields.Integer(string='Modules installés total', readonly=True)
    module_count_standard = fields.Integer(string='Modules standard Odoo', readonly=True)
    module_count_oca = fields.Integer(string='Modules OCA', readonly=True)
    module_count_custom = fields.Integer(string='Modules custom / tiers', readonly=True)

    # ── Synthèse données ──────────────────────────────────────────────────────
    total_records = fields.Integer(string='Enregistrements estimés total', readonly=True)
    has_multicompany = fields.Boolean(string='Multi-société', readonly=True)
    company_count = fields.Integer(string='Nombre de sociétés', readonly=True)
    custom_field_count = fields.Integer(string='Champs personnalisés (ir.model.fields)', readonly=True)
    server_action_python_count = fields.Integer(string='Actions Python serveur', readonly=True)
    automation_rule_count = fields.Integer(string='Règles d\'automatisation', readonly=True)

    # ── Lignes détail ─────────────────────────────────────────────────────────
    module_line_ids = fields.One2many(
        'migration.diagnostic.module', 'diagnostic_id',
        string='Modules analysés',
    )
    volume_line_ids = fields.One2many(
        'migration.diagnostic.volume', 'diagnostic_id',
        string='Volumes de données',
    )
    risk_line_ids = fields.One2many(
        'migration.diagnostic.risk', 'diagnostic_id',
        string='Facteurs de risque détectés',
    )

    # ── Recommandations ───────────────────────────────────────────────────────
    recommendation = fields.Html(string='Recommandations', readonly=True,
                                 sanitize=False, sanitize_attributes=False, sanitize_style=False)
    phase1_notes = fields.Html(string='Notes Phase 1 — Socle référentiel', readonly=True,
                               sanitize=False, sanitize_attributes=False, sanitize_style=False)
    phase2_notes = fields.Html(string='Notes Phase 2 — Données métier', readonly=True,
                               sanitize=False, sanitize_attributes=False, sanitize_style=False)
    error_message = fields.Text(string='Message d\'erreur', readonly=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('complexity_level')
    def _compute_complexity_color(self):
        colors = {'low': 10, 'medium': 3, 'high': 2, 'critical': 1}
        for rec in self:
            rec.complexity_color = colors.get(rec.complexity_level, 0)

    @api.depends('estimated_days_min', 'estimated_days_max')
    def _compute_estimated_days_label(self):
        for rec in self:
            if rec.estimated_days_min and rec.estimated_days_max:
                rec.estimated_days_label = f'{rec.estimated_days_min} – {rec.estimated_days_max} j/h'
            else:
                rec.estimated_days_label = _('N/A')

    # ─────────────────────────────────────────────────────────────────────────
    # Actions UI
    # ─────────────────────────────────────────────────────────────────────────

    def action_reset_draft(self):
        self.ensure_one()
        self.write({'state': 'draft', 'error_message': False})
        self.module_line_ids.unlink()
        self.volume_line_ids.unlink()
        self.risk_line_ids.unlink()

    def action_open_report(self):
        self.ensure_one()
        return self.env.ref('migration_diagnostic.action_report_migration_diagnostic').report_action(self)

    # ─────────────────────────────────────────────────────────────────────────
    # Moteur de scan principal
    # ─────────────────────────────────────────────────────────────────────────

    def action_run_scan(self, include_messages=True, include_attachments=True):
        self.ensure_one()
        import time
        t0 = time.time()
        self.write({'state': 'scanning', 'scan_date': fields.Datetime.now()})
        # Vider les lignes précédentes
        self.module_line_ids.unlink()
        self.volume_line_ids.unlink()
        self.risk_line_ids.unlink()

        try:
            self._scan_version()
            self._scan_modules()
            self._scan_volumes(
                include_messages=include_messages,
                include_attachments=include_attachments,
            )
            self._scan_customizations()
            self._compute_score()
            self._generate_recommendations()
            self.write({
                'state': 'done',
                'scan_duration': round(time.time() - t0, 2),
            })
        except Exception as e:
            _logger.exception('Erreur pendant le scan de migration')
            self.write({
                'state': 'error',
                'error_message': str(e),
            })
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Étapes du scan
    # ─────────────────────────────────────────────────────────────────────────

    def _scan_version(self):
        """Détecte la version Odoo courante."""
        release = self.env['ir.config_parameter'].get_param('web.base.url', '')
        try:
            import odoo.release as r
            version = r.version
        except Exception:
            version = 'Inconnue'
        self.source_version = version

    # Modules à exclure du scan (outils de migration/diagnostic eux-mêmes)
    EXCLUDED_MODULES = {
        'db_synchro', 'migration_diagnostic',
        'multi_db_sync', 'database_sync', 'odoo_migrate',
    }

    def _scan_modules(self):
        """Analyse les modules installés et les catégorise."""
        modules = self.env['ir.module.module'].search([('state', '=', 'installed')])
        ODOO_AUTHORS = {'odoo s.a.', 'odoo sa', 'odoo', 'openerp'}
        OCA_KEYWORDS = {'oca', 'odoo community association'}

        lines = []
        counts = {'standard': 0, 'oca': 0, 'custom': 0}

        for mod in modules:
            # Exclure les modules de migration/diagnostic (faux positifs)
            if mod.name in self.EXCLUDED_MODULES:
                continue

            author_lower = (mod.author or '').lower()
            if any(a in author_lower for a in ODOO_AUTHORS):
                category = 'standard'
            elif any(k in author_lower for k in OCA_KEYWORDS):
                category = 'oca'
            else:
                category = 'custom'
            counts[category] += 1

            # Risque du module
            risk = self._module_risk(mod, category)

            lines.append({
                'diagnostic_id': self.id,
                'name': mod.name,
                'technical_name': mod.technical_name if hasattr(mod, 'technical_name') else mod.name,
                'shortdesc': mod.shortdesc or '',
                'author': mod.author or '',
                'category': category,
                'risk_level': risk,
                'installed_version': mod.installed_version or '',
                'latest_version': mod.latest_version or '',
            })

        excluded_count = len(self.EXCLUDED_MODULES & set(modules.mapped('name')))
        self.env['migration.diagnostic.module'].create(lines)
        self.write({
            'module_count_total': len(modules) - excluded_count,
            'module_count_standard': counts['standard'],
            'module_count_oca': counts['oca'],
            'module_count_custom': counts['custom'],
        })

    def _module_risk(self, mod, category):
        """Évalue le risque d'un module pour la migration."""
        HIGH_RISK_MODULES = {
            'account_accountant', 'l10n_fr', 'l10n_fr_fec', 'l10n_fr_hr_payroll',
            'l10n_fr_reports', 'l10n_be', 'l10n_es', 'hr_payroll', 'hr_payroll_account',
            'mrp', 'mrp_subcontracting', 'quality_control', 'maintenance',
            'account_sepa', 'account_bank_statement_import', 'pos_restaurant',
            'l10n_ma', 'l10n_dz',
        }
        MEDIUM_RISK_MODULES = {
            'stock', 'mrp', 'purchase', 'account', 'hr', 'project', 'helpdesk',
            'sale_management', 'crm', 'website', 'ecommerce', 'fleet',
        }
        name = mod.name
        if category == 'custom':
            return 'high'
        if category == 'oca':
            return 'medium'
        if name in HIGH_RISK_MODULES:
            return 'medium'
        if name in MEDIUM_RISK_MODULES:
            return 'low'
        return 'low'

    def _scan_volumes(self, include_messages=True, include_attachments=True):
        """Mesure les volumes de données des modèles critiques."""
        MODELS_TO_SCAN = [
            # (model_name, label, phase, migration_priority)
            ('res.partner',          'Partenaires / Contacts',    '2', 1),
            ('res.users',            'Utilisateurs',              '1', 1),
            ('account.move',         'Pièces comptables',         '2', 5),
            ('account.move.line',    'Lignes comptables',         '2', 5),
            ('account.account',      'Plan comptable',            '1', 2),
            ('account.journal',      'Journaux',                  '1', 3),
            ('account.tax',          'Taxes',                     '1', 4),
            ('product.template',     'Fiches produit',            '2', 2),
            ('product.product',      'Variantes produit',         '2', 2),
            ('sale.order',           'Commandes client',          '2', 3),
            ('sale.order.line',      'Lignes commandes client',   '2', 3),
            ('purchase.order',       'Commandes fournisseur',     '2', 4),
            ('purchase.order.line',  'Lignes cmds fournisseur',   '2', 4),
            ('stock.picking',        'Transferts de stock',       '2', 6),
            ('stock.move',           'Mouvements de stock',       '2', 6),
            ('stock.warehouse',      'Entrepôts',                 '1', 5),
            ('mrp.production',       'Ordres de fabrication',     '2', 7),
            ('hr.employee',          'Employés',                  '2', 7),
            ('crm.lead',             'Opportunités CRM',          '2', 7),
        ]
        if include_messages:
            MODELS_TO_SCAN.append(('mail.message', 'Messages / Chatter', '2', 8))
        if include_attachments:
            MODELS_TO_SCAN.append(('ir.attachment', 'Pièces jointes', '2', 9))

        lines = []
        total = 0
        for model_name, label, phase, priority in MODELS_TO_SCAN:
            try:
                if model_name not in self.env:
                    count = 0
                    available = False
                else:
                    count = self.env[model_name].sudo().search_count([])
                    available = True
                    total += count

                volume_level = self._volume_level(count)
                lines.append({
                    'diagnostic_id': self.id,
                    'model_name': model_name,
                    'label': label,
                    'phase': phase,
                    'migration_priority': priority,
                    'record_count': count,
                    'volume_level': volume_level,
                    'available': available,
                })
            except Exception as e:
                _logger.warning('Impossible de compter %s : %s', model_name, e)

        self.env['migration.diagnostic.volume'].create(lines)
        self.total_records = total

    def _volume_level(self, count):
        if count == 0:
            return 'none'
        elif count < 1000:
            return 'low'
        elif count < 10000:
            return 'medium'
        elif count < 100000:
            return 'high'
        else:
            return 'critical'

    def _scan_customizations(self):
        """Détecte les facteurs de risque liés aux personnalisations."""
        risks = []

        # ── Multi-société ─────────────────────────────────────────────────────
        company_count = self.env['res.company'].search_count([])
        self.company_count = company_count
        self.has_multicompany = company_count > 1
        if company_count > 1:
            risks.append(self._mk_risk(
                'multi_company',
                'Multi-société détectée',
                f'{company_count} sociétés dans la base.',
                'high',
                'Chaque société nécessite une vérification des journaux, taxes et comptes. '
                'Les règles inter-sociétés peuvent nécessiter un reconfiguration manuelle.',
            ))

        # ── Champs custom ─────────────────────────────────────────────────────
        custom_fields = self.env['ir.model.fields'].search([
            ('state', '=', 'manual'),
        ])
        self.custom_field_count = len(custom_fields)
        if custom_fields:
            # Regrouper par modèle
            by_model = {}
            for f in custom_fields:
                by_model.setdefault(f.model_id.model, []).append(f.name)
            top_models = sorted(by_model.items(), key=lambda x: -len(x[1]))[:5]
            detail = ', '.join(f'{m}: {len(fs)} champs' for m, fs in top_models)
            risks.append(self._mk_risk(
                'custom_fields',
                f'{len(custom_fields)} champs personnalisés détectés',
                f'Modèles concernés : {detail}',
                'medium' if len(custom_fields) < 20 else 'high',
                'Les champs custom (x_*) doivent être recréés ou migrés via un module '
                'custom sur la base cible. Vérifier la compatibilité avec la nouvelle version.',
            ))

        # ── Actions Python serveur — uniquement celles sans xml_id (créées manuellement)
        all_python_actions = self.env['ir.actions.server'].search([
            ('state', '=', 'code'),
            ('binding_model_id', '!=', False),
        ])
        # Exclure celles livrées par un module Odoo (ont un xml_id avec module != '__custom__')
        xml_ids = self.env['ir.model.data'].search([
            ('model', '=', 'ir.actions.server'),
            ('res_id', 'in', all_python_actions.ids),
        ])
        standard_action_ids = set(xml_ids.mapped('res_id'))
        python_actions = all_python_actions.filtered(lambda a: a.id not in standard_action_ids)
        self.server_action_python_count = len(python_actions)
        if python_actions:
            risks.append(self._mk_risk(
                'python_server_actions',
                f'{len(python_actions)} actions serveur Python custom',
                'Des actions serveur avec du code Python ont été détectées (bindées sur des modèles).',
                'medium',
                'Le code Python des actions serveur peut nécessiter une adaptation '
                'lors de la migration (API Odoo modifiée entre versions).',
            ))

        # ── Règles d'automatisation ────────────────────────────────────────────
        # En v17, le modèle est toujours base.automation
        try:
            automation_model = 'base.automation'
            if automation_model in self.env:
                automations = self.env[automation_model].search([])
                self.automation_rule_count = len(automations)
                if automations:
                    risks.append(self._mk_risk(
                        'automation_rules',
                        f'{len(automations)} règles d\'automatisation',
                        'Des règles d\'automatisation sont configurées.',
                        'low',
                        'Les règles d\'automatisation sont généralement migrées automatiquement, '
                        'mais vérifier leur compatibilité avec la nouvelle version Odoo.',
                    ))
            else:
                self.automation_rule_count = 0
        except Exception:
            self.automation_rule_count = 0

        # ── Modules custom détectés ────────────────────────────────────────────
        if self.module_count_custom > 0:
            risks.append(self._mk_risk(
                'custom_modules',
                f'{self.module_count_custom} module(s) custom / tiers détecté(s)',
                'Ces modules nécessitent un portage vers la version cible.',
                'high' if self.module_count_custom > 3 else 'medium',
                'Chaque module custom doit être évalué individuellement : certains peuvent '
                'avoir une version compatible disponible, d\'autres nécessiteront un portage complet. '
                'Contacter les éditeurs ou prévoir le développement.',
            ))

        # ── Modules OCA ────────────────────────────────────────────────────────
        if self.module_count_oca > 0:
            risks.append(self._mk_risk(
                'oca_modules',
                f'{self.module_count_oca} module(s) OCA',
                'Les modules OCA sont généralement disponibles pour les nouvelles versions.',
                'low',
                'Vérifier la disponibilité de chaque module OCA pour la version cible '
                'sur https://github.com/OCA. La plupart sont disponibles rapidement après '
                'chaque nouvelle version d\'Odoo.',
            ))

        # ── Localisation détectée ─────────────────────────────────────────────
        l10n_modules = self.env['ir.module.module'].search([
            ('state', '=', 'installed'),
            ('name', 'like', 'l10n_'),
        ])
        if l10n_modules:
            l10n_names = ', '.join(l10n_modules.mapped('name'))
            risks.append(self._mk_risk(
                'localization',
                f'Localisation(s) détectée(s) : {l10n_names}',
                'Des modules de localisation comptable sont installés.',
                'medium',
                'Les localisations (plan comptable, TVA, FEC...) nécessitent une attention '
                'particulière lors de la migration. Vérifier la compatibilité avec la version '
                'cible et les obligations légales (facturation électronique pour l10n_fr).',
            ))

        # ── Volume pièces comptables ───────────────────────────────────────────
        if 'account.move' in self.env:
            move_count = self.env['account.move'].sudo().search_count([])
            if move_count > 50000:
                risks.append(self._mk_risk(
                    'accounting_volume',
                    f'Volume comptable élevé : {move_count:,} pièces',
                    'Un volume important de pièces comptables augmente la complexité.',
                    'high' if move_count > 200000 else 'medium',
                    'Prévoir une migration par segments (journal par journal, exercice par exercice). '
                    'Utiliser l\'opération "Segment Import" du module de synchronisation. '
                    'Valider les balances avant/après migration.',
                ))

        # ── Pièces jointes ────────────────────────────────────────────────────
        if 'ir.attachment' in self.env:
            attach_count = self.env['ir.attachment'].sudo().search_count([])
            if attach_count > 10000:
                risks.append(self._mk_risk(
                    'attachments_volume',
                    f'Volume pièces jointes : {attach_count:,} fichiers',
                    'Un volume important de pièces jointes ralentit la migration.',
                    'medium',
                    'Planifier la migration des pièces jointes en dernier. '
                    'Vérifier l\'espace disque disponible sur la base cible.',
                ))

        # ── Utilisateurs actifs ───────────────────────────────────────────────
        user_count = self.env['res.users'].search_count([('active', '=', True), ('share', '=', False)])
        if user_count > 50:
            risks.append(self._mk_risk(
                'users_count',
                f'{user_count} utilisateurs internes actifs',
                'Un nombre élevé d\'utilisateurs nécessite une validation des droits post-migration.',
                'low',
                'Prévoir une phase de validation des droits d\'accès et des règles de sécurité '
                'après migration. Les conflits de login sont gérés automatiquement par le moteur.',
            ))

        if risks:
            self.env['migration.diagnostic.risk'].create(risks)

    def _mk_risk(self, code, name, description, level, recommendation):
        return {
            'diagnostic_id': self.id,
            'code': code,
            'name': name,
            'description': description,
            'risk_level': level,
            'recommendation': recommendation,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Score global
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_score(self):
        """Calcule le score de complexité global (0-100) et estime la charge additivement."""
        score = 0

        # Modules custom (0-30)
        score += min(self.module_count_custom * 5, 30)
        # Modules OCA (0-10)
        score += min(self.module_count_oca * 1, 10)
        # Volume données (0-20)
        if self.total_records > 500000:
            score += 20
        elif self.total_records > 100000:
            score += 15
        elif self.total_records > 20000:
            score += 8
        elif self.total_records > 5000:
            score += 3
        # Multi-société (0-15)
        if self.has_multicompany:
            score += min(5 + (self.company_count - 2) * 3, 15)
        # Champs custom (0-15)
        score += min(self.custom_field_count // 5, 15)
        # Actions Python (0-5)
        score += min(self.server_action_python_count, 5)
        # Risques critiques (0-20)
        critical_risks = self.risk_line_ids.filtered(lambda r: r.risk_level == 'high')
        score += min(len(critical_risks) * 4, 20)

        # Socle incompressible de migration : même la plus simple demande
        # setup, recette et go-live. On plancher le score pour éviter un 0
        # trompeur (qui laisserait croire que le scan a échoué). Ce plancher
        # n'affecte que les bases triviales ; tout score >= 10 reste inchangé.
        MIN_COMPLEXITY_SCORE = 10
        self.complexity_score = min(max(score, MIN_COMPLEXITY_SCORE), 100)

        # Niveau
        if self.complexity_score < 20:
            level = 'low'
        elif self.complexity_score < 45:
            level = 'medium'
        elif self.complexity_score < 70:
            level = 'high'
        else:
            level = 'critical'
        self.complexity_level = level

        # ── Estimation additive (jours/homme intégrateur) ─────────────────
        days = 2.0  # base : setup + recette + go-live

        # Modules custom : 3j le 1er, 2j les suivants (économies d'échelle)
        if self.module_count_custom >= 1:
            days += 3 + (self.module_count_custom - 1) * 2

        # Modules OCA : 0.5j par module (vérif compatibilité + install)
        days += self.module_count_oca * 0.5

        # Multi-société : 3j par société supplémentaire
        if self.has_multicompany:
            days += (self.company_count - 1) * 3

        # Champs custom : 1j par tranche de 10
        days += (self.custom_field_count // 10) * 1.0

        # Actions Python : 0.5j par tranche de 5
        days += (self.server_action_python_count // 5) * 0.5

        # Volume données
        if self.total_records > 500000:
            days += 10
        elif self.total_records > 100000:
            days += 5
        elif self.total_records > 20000:
            days += 2

        # Localisation FR/BE/ES (compta, FEC, TVA)
        l10n_heavy = self.risk_line_ids.filtered(
            lambda r: r.code == 'localization' and
            any(k in (r.description or '') for k in ['l10n_fr', 'l10n_be', 'l10n_es'])
        )
        if l10n_heavy:
            days += 3

        # Risques élevés résiduels
        days += len(critical_risks) * 1.5

        # Fourchette : min = 80%, max = 160% (incertitude terrain)
        self.estimated_days_min = max(1, round(days * 0.8))
        self.estimated_days_max = max(2, round(days * 1.6))

    # ─────────────────────────────────────────────────────────────────────────
    # Recommandations HTML
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_recommendations(self):
        level = self.complexity_level

        styles = {
            'low':      ('success', '#d4edda', '#155724', '✅ Complexité FAIBLE'),
            'medium':   ('warning', '#fff3cd', '#856404', '⚠️ Complexité MOYENNE'),
            'high':     ('danger',  '#f8d7da', '#721c24', '🔴 Complexité ÉLEVÉE'),
            'critical': ('danger',  '#f5c6cb', '#491217', '🚨 Complexité CRITIQUE'),
        }
        _, bg, color, label = styles.get(level, styles['medium'])

        intros = {
            'low': "Votre installation est principalement composée de modules standard Odoo avec peu de personnalisations. Une migration peut être planifiée avec confiance.",
            'medium': "Des points d'attention ont été identifiés (modules OCA, champs custom, volumes modérés). Une migration est réalisable avec une préparation rigoureuse.",
            'high': "Des modules custom, des volumes importants ou des configurations spécifiques ont été détectés. Un accompagnement spécialisé est fortement recommandé.",
            'critical': "La combinaison de modules custom importants, de volumes élevés et de spécificités fonctionnelles nécessite un projet de migration structuré avec un expert Odoo.",
        }

        self.recommendation = f"""
<div style="background:{bg}; border-left:4px solid {color}; border-radius:4px; padding:16px; margin-bottom:8px;">
    <h4 style="color:{color}; margin:0 0 8px 0;">{label}</h4>
    <p style="margin:0; color:{color};">{intros.get(level, '')}</p>
</div>
<div style="display:flex; gap:16px; margin-top:12px;">
    <div style="flex:1; background:#f0f4ff; border:1px solid #c7d2fe; border-radius:6px; padding:14px;">
        <b style="color:#3730a3;">📊 Résumé de votre base</b>
        <ul style="margin:8px 0 0 0; padding-left:20px; line-height:1.8;">
            <li><b>{self.module_count_total}</b> modules installés ({self.module_count_custom} custom)</li>
            <li><b>{self.total_records:,}</b> enregistrements estimés</li>
            <li><b>{self.company_count}</b> société(s) — {'⚠️ multi-société' if self.has_multicompany else '✅ mono-société'}</li>
            <li><b>{self.custom_field_count}</b> champs personnalisés</li>
        </ul>
    </div>
    <div style="flex:1; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:14px;">
        <b style="color:#166534;">⏱️ Estimation de charge</b>
        <p style="margin:8px 0 0 0; font-size:22px; font-weight:bold; color:#166534;">{self.estimated_days_min} – {self.estimated_days_max} j/h</p>
        <p style="margin:4px 0 0 0; color:#666; font-size:12px;">Pour un intégrateur Odoo expérimenté</p>
    </div>
</div>
"""

        self.phase1_notes = """
<table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
        <tr style="background:#e8eaf6; color:#3730a3;">
            <th style="padding:8px 12px; text-align:left; width:4%;">#</th>
            <th style="padding:8px 12px; text-align:left; width:30%;">Modèle</th>
            <th style="padding:8px 12px; text-align:left; width:25%;">Opération</th>
            <th style="padding:8px 12px; text-align:left;">Points d'attention</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">1</td>
            <td style="padding:8px 12px;"><b>res.users</b><br/><span style="color:#888;font-size:11px;">Utilisateurs</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Migrer en <b>premier</b>. Conflits de login gérés automatiquement.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">2</td>
            <td style="padding:8px 12px;"><b>account.account</b><br/><span style="color:#888;font-size:11px;">Plan comptable</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Faire un <b>Link Mapping</b> sur les comptes existants avant l'import.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">3</td>
            <td style="padding:8px 12px;"><b>account.journal</b><br/><span style="color:#888;font-size:11px;">Journaux</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Vérifier les codes journaux après import.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">4</td>
            <td style="padding:8px 12px;"><b>account.tax</b><br/><span style="color:#888;font-size:11px;">Taxes</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Attention aux codes renommés entre versions Odoo.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">5</td>
            <td style="padding:8px 12px;"><b>stock.warehouse</b><br/><span style="color:#888;font-size:11px;">Entrepôts</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ Création MANUELLE</span></td>
            <td style="padding:8px 12px;">Ne pas migrer via le module. Créer manuellement + Link Mapping.</td>
        </tr>
        <tr style="background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">6</td>
            <td style="padding:8px 12px;"><b>stock.picking.type</b><br/><span style="color:#888;font-size:11px;">Types d'opération</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ Mapping MANUEL</span></td>
            <td style="padding:8px 12px;">Créés par l'entrepôt Odoo. Utiliser link_mapping pour aligner les IDs.</td>
        </tr>
    </tbody>
</table>
"""

        self.phase2_notes = """
<table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
        <tr style="background:#e8eaf6; color:#3730a3;">
            <th style="padding:8px 12px; text-align:left; width:4%;">#</th>
            <th style="padding:8px 12px; text-align:left; width:30%;">Modèle</th>
            <th style="padding:8px 12px; text-align:left; width:25%;">Opération</th>
            <th style="padding:8px 12px; text-align:left;">Points d'attention</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">1</td>
            <td style="padding:8px 12px;"><b>res.partner</b><br/><span style="color:#888;font-size:11px;">Partenaires</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit Unsynced</span></td>
            <td style="padding:8px 12px;">Attention aux partenaires liés à des utilisateurs (éviter les doublons).</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">2</td>
            <td style="padding:8px 12px;"><b>product.template</b><br/><span style="color:#888;font-size:11px;">Produits</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import Datas</span></td>
            <td style="padding:8px 12px;">Le hook gère automatiquement les variantes. Ne pas lancer product.product séparément.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">3</td>
            <td style="padding:8px 12px;"><b>sale.order</b><br/><span style="color:#888;font-size:11px;">Commandes client</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit → Specific</span></td>
            <td style="padding:8px 12px;">Vérifier les états (draft/confirmed/done). Lignes migrées via O2M.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">4</td>
            <td style="padding:8px 12px;"><b>purchase.order</b><br/><span style="color:#888;font-size:11px;">Commandes fourn.</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit → Specific</span></td>
            <td style="padding:8px 12px;">Même logique que sale.order. Vérifier les taxes sur lignes.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">5</td>
            <td style="padding:8px 12px;"><b>account.move</b><br/><span style="color:#888;font-size:11px;">Pièces comptables</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef2f2;color:#991b1b;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ Segment Import</span></td>
            <td style="padding:8px 12px;">Migrer <b>journal par journal</b>. Lancer <code>create_queue_for_unbalanced_moves</code> après chaque batch.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">6</td>
            <td style="padding:8px 12px;"><b>stock.picking</b><br/><span style="color:#888;font-size:11px;">Transferts stock</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import Datas</span></td>
            <td style="padding:8px 12px;">Mouvements et lignes gérés récursivement (O2M). Vérifier l'état des transferts.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">7</td>
            <td style="padding:8px 12px;"><b>mail.message</b><br/><span style="color:#888;font-size:11px;">Chatter</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import par modèle</span></td>
            <td style="padding:8px 12px;">Utiliser le domaine <code>res_model = 'sale.order'</code>. Parents migrés en premier.</td>
        </tr>
        <tr style="background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">8</td>
            <td style="padding:8px 12px;"><b>ir.attachment</b><br/><span style="color:#888;font-size:11px;">Pièces jointes</span></td>
            <td style="padding:8px 12px;"><span style="background:#f0fdf4;color:#166534;padding:2px 8px;border-radius:4px;font-size:11px;">Import EN DERNIER</span></td>
            <td style="padding:8px 12px;">Migrer en dernier. Vérifier les volumes (espace disque).</td>
        </tr>
    </tbody>
</table>
<div style="background:#fef3c7; border:1px solid #fcd34d; border-radius:6px; padding:12px; margin-top:12px;">
    <b style="color:#92400e;">⚠️ Règle d'or :</b>
    <span style="color:#92400e;"> TOUJOURS valider chaque modèle avant de passer au suivant.<br/>
    Workflow : <code>Import</code> → <code>Audit Unsynced</code> → <code>Import Specific</code> sur erreurs → <code>Validate</code></span>
</div>
"""
