import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MigrationDiagnostic(models.Model):
    _name = 'migration.diagnostic'
    _description = 'Odoo Migration Diagnostic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Identité ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        required=True,
        default=lambda self: _('Diagnostic of %s') % fields.Datetime.now().strftime('%d/%m/%Y %H:%M'),
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scanning', 'Analyzing...'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], default='draft', string='Status', tracking=True)

    source_version = fields.Char(string='Source Odoo version', readonly=True)
    scan_date = fields.Datetime(string='Scan date', readonly=True)
    scan_duration = fields.Float(string='Scan duration (s)', readonly=True)

    # ── Résultats ─────────────────────────────────────────────────────────────
    complexity_score = fields.Integer(
        string='Complexity score',
        readonly=True,
        help='Global score from 0 to 100. The higher it is, the more complex the migration.',
    )
    complexity_level = fields.Selection([
        ('low',      'Low ✅'),
        ('medium',   'Medium ⚠️'),
        ('high',     'High 🔴'),
        ('critical', 'Critical 🚨'),
    ], string='Complexity level', readonly=True, tracking=True)
    complexity_color = fields.Integer(compute='_compute_complexity_color')

    estimated_days_min = fields.Integer(string='Estimated effort min (days)', readonly=True)
    estimated_days_max = fields.Integer(string='Estimated effort max (days)', readonly=True)
    estimated_days_label = fields.Char(compute='_compute_estimated_days_label', string='Estimate')

    # ── Synthèse modules ──────────────────────────────────────────────────────
    module_count_total = fields.Integer(string='Total installed modules', readonly=True)
    module_count_standard = fields.Integer(string='Standard Odoo modules', readonly=True)
    module_count_oca = fields.Integer(string='OCA modules', readonly=True)
    module_count_custom = fields.Integer(string='Custom / third-party modules', readonly=True)

    # ── Synthèse données ──────────────────────────────────────────────────────
    total_records = fields.Integer(string='Total estimated records', readonly=True)
    has_multicompany = fields.Boolean(string='Multi-company', readonly=True)
    company_count = fields.Integer(string='Number of companies', readonly=True)
    custom_field_count = fields.Integer(string='Custom fields (ir.model.fields)', readonly=True)
    server_action_python_count = fields.Integer(string='Python server actions', readonly=True)
    automation_rule_count = fields.Integer(string='Automation rules', readonly=True)

    # ── Lignes détail ─────────────────────────────────────────────────────────
    module_line_ids = fields.One2many(
        'migration.diagnostic.module', 'diagnostic_id',
        string='Analyzed modules',
    )
    volume_line_ids = fields.One2many(
        'migration.diagnostic.volume', 'diagnostic_id',
        string='Data volumes',
    )
    risk_line_ids = fields.One2many(
        'migration.diagnostic.risk', 'diagnostic_id',
        string='Detected risk factors',
    )

    # ── Recommandations ───────────────────────────────────────────────────────
    recommendation = fields.Html(string='Recommendations', readonly=True,
                                 sanitize=False, sanitize_attributes=False, sanitize_style=False)
    phase1_notes = fields.Html(string='Phase 1 notes — Reference data', readonly=True,
                               sanitize=False, sanitize_attributes=False, sanitize_style=False)
    phase2_notes = fields.Html(string='Phase 2 notes — Business data', readonly=True,
                               sanitize=False, sanitize_attributes=False, sanitize_style=False)
    error_message = fields.Text(string='Error message', readonly=True)

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
                rec.estimated_days_label = _('%(min)s – %(max)s days') % {
                    'min': rec.estimated_days_min, 'max': rec.estimated_days_max}
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
            ('res.partner',          _('Partners / Contacts'),    '2', 1),
            ('res.users',            _('Users'),                  '1', 1),
            ('account.move',         _('Journal entries'),        '2', 5),
            ('account.move.line',    _('Journal items'),          '2', 5),
            ('account.account',      _('Chart of accounts'),      '1', 2),
            ('account.journal',      _('Journals'),               '1', 3),
            ('account.tax',          _('Taxes'),                  '1', 4),
            ('product.template',     _('Product templates'),      '2', 2),
            ('product.product',      _('Product variants'),       '2', 2),
            ('sale.order',           _('Sales orders'),           '2', 3),
            ('sale.order.line',      _('Sales order lines'),      '2', 3),
            ('purchase.order',       _('Purchase orders'),        '2', 4),
            ('purchase.order.line',  _('Purchase order lines'),   '2', 4),
            ('stock.picking',        _('Stock transfers'),        '2', 6),
            ('stock.move',           _('Stock moves'),            '2', 6),
            ('stock.warehouse',      _('Warehouses'),             '1', 5),
            ('mrp.production',       _('Manufacturing orders'),   '2', 7),
            ('hr.employee',          _('Employees'),              '2', 7),
            ('crm.lead',             _('CRM leads'),              '2', 7),
        ]
        if include_messages:
            MODELS_TO_SCAN.append(('mail.message', _('Messages / Chatter'), '2', 8))
        if include_attachments:
            MODELS_TO_SCAN.append(('ir.attachment', _('Attachments'), '2', 9))

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
                _('Multi-company detected'),
                _('%s companies in the database.') % company_count,
                'high',
                _('Each company requires checking journals, taxes and accounts. '
                  'Inter-company rules may need manual reconfiguration.'),
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
            detail = ', '.join(_('%(model)s: %(count)s fields') % {'model': m, 'count': len(fs)} for m, fs in top_models)
            risks.append(self._mk_risk(
                'custom_fields',
                _('%s custom fields detected') % len(custom_fields),
                _('Models involved: %s') % detail,
                'medium' if len(custom_fields) < 20 else 'high',
                _('Custom fields (x_*) must be recreated or migrated through a custom '
                  'module on the target database. Check compatibility with the new version.'),
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
                _('%s custom Python server actions') % len(python_actions),
                _('Server actions with Python code have been detected (bound to models).'),
                'medium',
                _('The Python code of server actions may need to be adapted '
                  'during migration (Odoo API changed between versions).'),
            ))

        # ── Règles d'automatisation ────────────────────────────────────────────
        # Le modèle des automatisations est base.automation (v15+)
        try:
            automation_model = 'base.automation'
            if automation_model in self.env:
                automations = self.env[automation_model].search([])
                self.automation_rule_count = len(automations)
                if automations:
                    risks.append(self._mk_risk(
                        'automation_rules',
                        _('%s automation rules') % len(automations),
                        _('Automation rules are configured.'),
                        'low',
                        _('Automation rules are usually migrated automatically, '
                          'but check their compatibility with the new Odoo version.'),
                    ))
            else:
                self.automation_rule_count = 0
        except Exception:
            self.automation_rule_count = 0

        # ── Modules custom détectés ────────────────────────────────────────────
        if self.module_count_custom > 0:
            risks.append(self._mk_risk(
                'custom_modules',
                _('%s custom / third-party module(s) detected') % self.module_count_custom,
                _('These modules require porting to the target version.'),
                'high' if self.module_count_custom > 3 else 'medium',
                _('Each custom module must be assessed individually: some may '
                  'have a compatible version available, others will require a full port. '
                  'Contact the publishers or plan the development.'),
            ))

        # ── Modules OCA ────────────────────────────────────────────────────────
        if self.module_count_oca > 0:
            risks.append(self._mk_risk(
                'oca_modules',
                _('%s OCA module(s)') % self.module_count_oca,
                _('OCA modules are usually available for new versions.'),
                'low',
                _('Check the availability of each OCA module for the target version '
                  'on https://github.com/OCA. Most are available shortly after '
                  'each new Odoo release.'),
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
                _('Localization(s) detected: %s') % l10n_names,
                _('Accounting localization modules are installed.'),
                'medium',
                _('Localizations (chart of accounts, VAT, FEC...) require special '
                  'attention during migration. Check compatibility with the target '
                  'version and legal obligations (electronic invoicing for l10n_fr).'),
            ))

        # ── Volume pièces comptables ───────────────────────────────────────────
        if 'account.move' in self.env:
            move_count = self.env['account.move'].sudo().search_count([])
            if move_count > 50000:
                risks.append(self._mk_risk(
                    'accounting_volume',
                    _('High accounting volume: %s entries') % '{:,}'.format(move_count),
                    _('A large volume of journal entries increases complexity.'),
                    'high' if move_count > 200000 else 'medium',
                    _('Plan a segmented migration (journal by journal, fiscal year by fiscal year). '
                      'Use the "Segment Import" operation of the synchronization module. '
                      'Validate balances before/after migration.'),
                ))

        # ── Pièces jointes ────────────────────────────────────────────────────
        if 'ir.attachment' in self.env:
            attach_count = self.env['ir.attachment'].sudo().search_count([])
            if attach_count > 10000:
                risks.append(self._mk_risk(
                    'attachments_volume',
                    _('Attachments volume: %s files') % '{:,}'.format(attach_count),
                    _('A large volume of attachments slows down migration.'),
                    'medium',
                    _('Plan the attachments migration last. '
                      'Check available disk space on the target database.'),
                ))

        # ── Utilisateurs actifs ───────────────────────────────────────────────
        user_count = self.env['res.users'].search_count([('active', '=', True), ('share', '=', False)])
        if user_count > 50:
            risks.append(self._mk_risk(
                'users_count',
                _('%s active internal users') % user_count,
                _('A high number of users requires validating access rights after migration.'),
                'low',
                _('Plan a phase to validate access rights and security rules '
                  'after migration. Login conflicts are handled automatically by the engine.'),
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
            'low':      ('success', '#d4edda', '#155724', _('✅ Complexity LOW')),
            'medium':   ('warning', '#fff3cd', '#856404', _('⚠️ Complexity MEDIUM')),
            'high':     ('danger',  '#f8d7da', '#721c24', _('🔴 Complexity HIGH')),
            'critical': ('danger',  '#f5c6cb', '#491217', _('🚨 Complexity CRITICAL')),
        }
        _dummy, bg, color, label = styles.get(level, styles['medium'])

        intros = {
            'low': _("Your installation is mainly made of standard Odoo modules with few customizations. A migration can be planned with confidence."),
            'medium': _("Some points of attention have been identified (OCA modules, custom fields, moderate volumes). A migration is achievable with rigorous preparation."),
            'high': _("Custom modules, large volumes or specific configurations have been detected. Specialized support is strongly recommended."),
            'critical': _("The combination of significant custom modules, high volumes and functional specifics requires a structured migration project with an Odoo expert."),
        }

        multi = _('⚠️ multi-company') if self.has_multicompany else _('✅ mono-company')

        self.recommendation = _("""
<div style="background:%(bg)s; border-left:4px solid %(color)s; border-radius:4px; padding:16px; margin-bottom:8px;">
    <h4 style="color:%(color)s; margin:0 0 8px 0;">%(label)s</h4>
    <p style="margin:0; color:%(color)s;">%(intro)s</p>
</div>
<div style="display:flex; gap:16px; margin-top:12px;">
    <div style="flex:1; background:#f0f4ff; border:1px solid #c7d2fe; border-radius:6px; padding:14px;">
        <b style="color:#3730a3;">📊 Summary of your database</b>
        <ul style="margin:8px 0 0 0; padding-left:20px; line-height:1.8;">
            <li><b>%(modules_total)s</b> installed modules (%(modules_custom)s custom)</li>
            <li><b>%(records)s</b> estimated records</li>
            <li><b>%(companies)s</b> company(ies) — %(multi)s</li>
            <li><b>%(custom_fields)s</b> custom fields</li>
        </ul>
    </div>
    <div style="flex:1; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:14px;">
        <b style="color:#166534;">⏱️ Effort estimate</b>
        <p style="margin:8px 0 0 0; font-size:22px; font-weight:bold; color:#166534;">%(days_min)s – %(days_max)s days</p>
        <p style="margin:4px 0 0 0; color:#666; font-size:12px;">For an experienced Odoo integrator</p>
    </div>
</div>
""") % {
            'bg': bg, 'color': color, 'label': label, 'intro': intros.get(level, ''),
            'modules_total': self.module_count_total, 'modules_custom': self.module_count_custom,
            'records': '{:,}'.format(self.total_records), 'companies': self.company_count,
            'multi': multi, 'custom_fields': self.custom_field_count,
            'days_min': self.estimated_days_min, 'days_max': self.estimated_days_max,
        }

        self.phase1_notes = _("""
<table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
        <tr style="background:#e8eaf6; color:#3730a3;">
            <th style="padding:8px 12px; text-align:left; width:4%;">#</th>
            <th style="padding:8px 12px; text-align:left; width:30%;">Model</th>
            <th style="padding:8px 12px; text-align:left; width:25%;">Operation</th>
            <th style="padding:8px 12px; text-align:left;">Watch-outs</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">1</td>
            <td style="padding:8px 12px;"><b>res.users</b><br/><span style="color:#888;font-size:11px;">Users</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Migrate <b>first</b>. Login conflicts handled automatically.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">2</td>
            <td style="padding:8px 12px;"><b>account.account</b><br/><span style="color:#888;font-size:11px;">Chart of accounts</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Do a <b>Link Mapping</b> on existing accounts before import.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">3</td>
            <td style="padding:8px 12px;"><b>account.journal</b><br/><span style="color:#888;font-size:11px;">Journals</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Check journal codes after import.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">4</td>
            <td style="padding:8px 12px;"><b>account.tax</b><br/><span style="color:#888;font-size:11px;">Taxes</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import + Link Mapping</span></td>
            <td style="padding:8px 12px;">Beware of codes renamed between Odoo versions.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">5</td>
            <td style="padding:8px 12px;"><b>stock.warehouse</b><br/><span style="color:#888;font-size:11px;">Warehouses</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ MANUAL creation</span></td>
            <td style="padding:8px 12px;">Do not migrate via the module. Create manually + Link Mapping.</td>
        </tr>
        <tr style="background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">6</td>
            <td style="padding:8px 12px;"><b>stock.picking.type</b><br/><span style="color:#888;font-size:11px;">Operation types</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ MANUAL mapping</span></td>
            <td style="padding:8px 12px;">Created by the Odoo warehouse. Use link_mapping to align the IDs.</td>
        </tr>
    </tbody>
</table>
""")

        self.phase2_notes = _("""
<table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
        <tr style="background:#e8eaf6; color:#3730a3;">
            <th style="padding:8px 12px; text-align:left; width:4%;">#</th>
            <th style="padding:8px 12px; text-align:left; width:30%;">Model</th>
            <th style="padding:8px 12px; text-align:left; width:25%;">Operation</th>
            <th style="padding:8px 12px; text-align:left;">Watch-outs</th>
        </tr>
    </thead>
    <tbody>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">1</td>
            <td style="padding:8px 12px;"><b>res.partner</b><br/><span style="color:#888;font-size:11px;">Partners</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit Unsynced</span></td>
            <td style="padding:8px 12px;">Beware of partners linked to users (avoid duplicates).</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">2</td>
            <td style="padding:8px 12px;"><b>product.template</b><br/><span style="color:#888;font-size:11px;">Products</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import Datas</span></td>
            <td style="padding:8px 12px;">The hook handles variants automatically. Do not run product.product separately.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">3</td>
            <td style="padding:8px 12px;"><b>sale.order</b><br/><span style="color:#888;font-size:11px;">Sales orders</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit → Specific</span></td>
            <td style="padding:8px 12px;">Check states (draft/confirmed/done). Lines migrated via O2M.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">4</td>
            <td style="padding:8px 12px;"><b>purchase.order</b><br/><span style="color:#888;font-size:11px;">Purchase orders</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import → Audit → Specific</span></td>
            <td style="padding:8px 12px;">Same logic as sale.order. Check taxes on lines.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">5</td>
            <td style="padding:8px 12px;"><b>account.move</b><br/><span style="color:#888;font-size:11px;">Journal entries</span></td>
            <td style="padding:8px 12px;"><span style="background:#fef2f2;color:#991b1b;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ Segment Import</span></td>
            <td style="padding:8px 12px;">Migrate <b>journal by journal</b>. Run <code>create_queue_for_unbalanced_moves</code> after each batch.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb; background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">6</td>
            <td style="padding:8px 12px;"><b>stock.picking</b><br/><span style="color:#888;font-size:11px;">Stock transfers</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import Datas</span></td>
            <td style="padding:8px 12px;">Moves and lines handled recursively (O2M). Check the transfer state.</td>
        </tr>
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">7</td>
            <td style="padding:8px 12px;"><b>mail.message</b><br/><span style="color:#888;font-size:11px;">Chatter</span></td>
            <td style="padding:8px 12px;"><span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:4px;font-size:11px;">Import per model</span></td>
            <td style="padding:8px 12px;">Use the domain <code>res_model = 'sale.order'</code>. Parents migrated first.</td>
        </tr>
        <tr style="background:#fafafa;">
            <td style="padding:8px 12px; font-weight:bold; color:#3730a3;">8</td>
            <td style="padding:8px 12px;"><b>ir.attachment</b><br/><span style="color:#888;font-size:11px;">Attachments</span></td>
            <td style="padding:8px 12px;"><span style="background:#f0fdf4;color:#166534;padding:2px 8px;border-radius:4px;font-size:11px;">Import LAST</span></td>
            <td style="padding:8px 12px;">Migrate last. Check volumes (disk space).</td>
        </tr>
    </tbody>
</table>
<div style="background:#fef3c7; border:1px solid #fcd34d; border-radius:6px; padding:12px; margin-top:12px;">
    <b style="color:#92400e;">⚠️ Golden rule:</b>
    <span style="color:#92400e;"> ALWAYS validate each model before moving to the next.<br/>
    Workflow: <code>Import</code> → <code>Audit Unsynced</code> → <code>Import Specific</code> on errors → <code>Validate</code></span>
</div>
""")
