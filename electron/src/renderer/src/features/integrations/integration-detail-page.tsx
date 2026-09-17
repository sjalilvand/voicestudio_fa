import { ArrowLeftIcon, ExternalLinkIcon, BlocksIcon } from 'lucide-react';
import { Link, useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { WorkspaceHeader } from '@/components/app-shell/workspace-header';
import { getBridge } from '@/components/bridge';
import { getIntegrationBySlug } from '../../../../../../frontend/src/config/integration-catalog';
import './integrations-page.css';

const categoryLabels: Record<string, [string, string]> = {
  comms: ['nav.dub', 'Calling & voice agents'],
  automation: ['tools.title', 'Automation'],
  agents: ['dub.choose_translation_agent', 'Agents'],
  mcp: ['settings.mcp_title', 'MCP'],
  developer: ['tools.title', 'Developer tools'],
  data: ['engineSidebar.asr', 'AI and data'],
  productivity: ['tools.title', 'Productivity'],
};

export function IntegrationDetailPage() {
  const { t } = useTranslation();
  const { slug } = useParams({ strict: false });
  const entry = getIntegrationBySlug(slug ?? '');
  if (!entry) {
    return (
      <div className="integrations-page">
        <WorkspaceHeader><h1 className="text-sm font-medium">{t('integrationCatalog.title')}</h1></WorkspaceHeader>
        <main className="integrations-content integrations-detail-empty">
          <p>{t('common.no_matches')}</p>
          <Link to="/integrations" className="integration-back-link"><ArrowLeftIcon />{t('common.back')}</Link>
        </main>
      </div>
    );
  }
  const [categoryKey, categoryFallback] = categoryLabels[entry.category] ?? ['tools.title', 'Integration'];
  const openExternal = () => {
    const bridge = getBridge();
    if (bridge) void bridge.files.openExternal(entry.url);
    else window.open(entry.url, '_blank', 'noopener,noreferrer');
  };
  return (
    <div className="integrations-page">
      <WorkspaceHeader><h1 className="text-sm font-medium">{entry.name}</h1></WorkspaceHeader>
      <main className="integrations-content integrations-detail">
        <Link to="/integrations" className="integration-back-link"><ArrowLeftIcon />{t('common.back')}</Link>
        <section className="integration-detail-hero">
          <div className="integration-detail-logo"><img src={entry.logoUrl} alt="" /></div>
          <div>
            <p className="integration-detail-kicker"><BlocksIcon />{t(categoryKey, { defaultValue: categoryFallback })}</p>
            <h2>{entry.name}</h2>
            <p>{t('integrationCatalog.description')}</p>
          </div>
        </section>
        <div className="integration-detail-grid">
          <section className="integration-detail-panel">
            <h3>{t('common.details')}</h3>
            <div className="integration-capabilities">
              {entry.detailKeys.map((key) => <span key={key}>{t(key)}</span>)}
            </div>
            <p className="integration-detail-note">{t('directoryExamples.notice')}</p>
          </section>
          <section className="integration-detail-panel integration-detail-action">
            <h3>{t('common.details')}</h3>
            <p className="integration-detail-url">{entry.url}</p>
            <button type="button" onClick={openExternal} className="integration-open-button">
              {t('common.open')}<ExternalLinkIcon />
            </button>
          </section>
        </div>
      </main>
    </div>
  );
}
