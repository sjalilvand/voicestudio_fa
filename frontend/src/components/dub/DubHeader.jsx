import {
  FileText,
  Save,
  RotateCcw,
  Loader,
  Square,
  Play,
  Download,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '../../ui';
import FooterBtn from './FooterBtn';
import DubPipelineStepper from './DubPipelineStepper';
import { formatTime } from '../../utils/format';

export default function DubHeader({
  t,
  dubFilename,
  dubDuration,
  dubSegments,
  activeProjectName,
  saveProject,
  resetDub,
  dubStep,
  handleDubStop,
  dubProgress,
  onGenerateClick,
  isTranslating,
  multiLangMode,
  multiLangs,
  incrementalPlan,
  handleDubGenerate,
  qcRunning,
  handleDubQc,
  setExportOpen,
  pipelineSteps,
  onPipelineStep,
}) {
  const generateLabel =
    multiLangMode && multiLangs.length > 1
      ? t('dub.generate_dub_multi', {
          count: multiLangs.length,
          defaultValue: 'Generate {{count}} dubs',
        })
      : t('dub.generate_dub');

  return (
    <div
      className="dub-command-bar"
      data-testid="dub-command-bar"
      role="toolbar"
      aria-label={t('dub.video_dubbing_studio')}
    >
      <div className="dub-command-bar__identity">
        <span className="dub-command-bar__file" aria-hidden="true">
          <FileText size={13} />
        </span>
        <div className="min-w-0">
          <div className="dub-command-bar__title" title={dubFilename}>
            {dubFilename}
          </div>
          <div className="dub-command-bar__meta">
            <span>{formatTime(dubDuration)}</span>
            <span aria-hidden="true">·</span>
            <span>
              {dubSegments.length} {t('dub.segs')}
            </span>
            {activeProjectName && activeProjectName !== dubFilename && (
              <>
                <span aria-hidden="true">·</span>
                <span className="dub-command-bar__project" title={activeProjectName}>
                  {activeProjectName}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <DubPipelineStepper
        dubStep={dubStep}
        inline
        variant="command"
        selectableSteps={pipelineSteps}
        onStepSelect={onPipelineStep}
      />

      <div className="dub-command-bar__actions">
        <div className="dub-command-bar__utilities">
          <Button
            variant="subtle"
            size="sm"
            className="!size-[26px] !p-0"
            onClick={saveProject}
            title={t('dub.save')}
            aria-label={t('dub.save')}
          >
            <Save size={12} />
          </Button>
          <Button
            variant="danger"
            size="sm"
            className="!size-[26px] !p-0"
            onClick={resetDub}
            title={t('dub.reset')}
            aria-label={t('dub.reset')}
          >
            <RotateCcw size={12} />
          </Button>
        </div>

        {dubStep === 'stopping' ? (
          <FooterBtn
            sm
            tone="stopping"
            disabled
            className="dub-command-bar__primary"
            icon={<Loader className="spinner" size={10} />}
            label={t('dub.stopping')}
          />
        ) : dubStep === 'generating' ? (
          <FooterBtn
            sm
            tone="danger"
            className="dub-command-bar__primary"
            onClick={handleDubStop}
            icon={<Square size={9} />}
            label={t('dub.stop_progress', {
              current: dubProgress.current,
              total: dubProgress.total,
            })}
          />
        ) : (
          <>
            <FooterBtn
              sm
              tone={dubSegments.length && !isTranslating ? 'pink' : 'idle'}
              className="dub-command-bar__primary"
              onClick={onGenerateClick}
              disabled={!dubSegments.length || isTranslating}
              icon={<Play size={11} />}
              label={generateLabel}
              aria-label={generateLabel}
            />
            {dubStep === 'done' && incrementalPlan && incrementalPlan.stale?.length > 0 && (
              <FooterBtn
                sm
                tone="pink"
                onClick={() =>
                  handleDubGenerate({ regenOnly: incrementalPlan.stale, preview: true })
                }
                icon={<Play size={11} />}
                label={t('dub.regen_changed', { count: incrementalPlan.stale.length })}
              />
            )}
          </>
        )}

        {dubStep === 'done' && (
          <FooterBtn
            sm
            tone="idle"
            disabled={qcRunning || !dubSegments.length}
            onClick={handleDubQc}
            icon={qcRunning ? <Loader className="spinner" size={11} /> : <ShieldCheck size={11} />}
            title={t('dub.qc_btn', { defaultValue: 'Verify dub timing (second-pass check)' })}
            aria-label={t('dub.qc_btn', {
              defaultValue: 'Verify dub timing (second-pass check)',
            })}
          />
        )}
        <FooterBtn
          sm
          tone={dubStep === 'done' ? 'green' : 'idle'}
          disabled={dubStep !== 'done' && !dubSegments.length}
          onClick={() => setExportOpen(true)}
          icon={<Download size={12} />}
          title={t('dub.export_btn')}
          aria-label={t('dub.export_btn')}
        />
      </div>
    </div>
  );
}
