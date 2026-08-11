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
  return (
    <div className="flex flex-col gap-[2px] min-w-0 px-[10px] py-[4px] shrink-0 bg-[var(--color-bg-elev-1)] rounded-md mb-[2px]">
      {/* Row 1: project title (left) + actions (right). Row 2: the pipeline
          spine (Upload → … → Export) sits directly under the title with a
          tight 2px gap — title-first, owner-requested order. */}
      <div className="flex flex-wrap justify-between items-center gap-x-[var(--space-2)] gap-y-[4px] min-w-0">
        <div className="label-row dub-head__title !gap-[6px]">
          <FileText className="label-icon" size={11} aria-hidden="true" />
          <span className="font-medium text-[0.78rem] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-fg normal-case">
            {dubFilename}
          </span>
          <span className="text-fg-muted font-normal whitespace-nowrap text-[0.68rem] normal-case shrink-0">
            · {formatTime(dubDuration)} · {dubSegments.length} {t('dub.segs')}
          </span>
          {activeProjectName && activeProjectName !== dubFilename && (
            <span className="text-[#b8bb26] ml-[var(--space-2)] whitespace-nowrap text-[0.68rem] normal-case overflow-hidden text-ellipsis min-w-0">
              — {activeProjectName}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-[6px] items-center justify-end shrink-0 [.shell-mini_&]:w-full">
          {/* Icon-only secondary actions (tooltips carry the labels);
                  Generate Dub keeps its label as the primary verb. */}
          <Button
            variant="subtle"
            size="sm"
            onClick={saveProject}
            title={t('dub.save')}
            aria-label={t('dub.save')}
          >
            <Save size={12} aria-hidden="true" />
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={resetDub}
            title={t('dub.reset')}
            aria-label={t('dub.reset')}
          >
            <RotateCcw size={12} aria-hidden="true" />
          </Button>
          {/* Primary actions live on the header bar (compact) — moved up from the footer. */}
          <div
            className="flex flex-wrap items-center justify-end gap-[4px] rounded-[var(--chrome-radius-pill)] bg-[color-mix(in_srgb,var(--color-bg-elev-2)_78%,transparent)] p-[3px] shadow-[var(--shadow-md)] [.shell-mini_&]:w-full"
            data-testid="dub-primary-actions"
          >
            {dubStep === 'stopping' ? (
              <FooterBtn
                sm
                tone="stopping"
                disabled
                className="!flex-none [.shell-mini_&]:flex-1"
                icon={<Loader className="spinner" size={9} aria-hidden="true" />}
                label={t('dub.stopping')}
                aria-busy="true"
              />
            ) : dubStep === 'generating' ? (
              <FooterBtn
                sm
                tone="danger"
                className="!flex-none hover:-translate-y-px active:translate-y-0 motion-reduce:transform-none [.shell-mini_&]:flex-1"
                onClick={handleDubStop}
                icon={<Square size={9} aria-hidden="true" />}
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
                  className="dub-action-btn--generate !h-[30px] !flex-none !px-[11px] !text-[0.68rem] !font-semibold !tracking-[0.015em] enabled:hover:-translate-y-px enabled:active:translate-y-0 motion-reduce:transform-none enabled:shadow-[0_5px_14px_color-mix(in_srgb,var(--chrome-accent)_18%,transparent)] enabled:hover:shadow-[0_7px_18px_color-mix(in_srgb,var(--chrome-accent)_26%,transparent)] [.shell-mini_&]:flex-1"
                  onClick={onGenerateClick}
                  // The multi-language batch translates between generates while
                  // dubStep briefly sits back at 'editing' — keep the CTA inert
                  // during that phase so a re-click can't start a second batch.
                  disabled={!dubSegments.length || isTranslating}
                  icon={<Play className="fill-current" size={11} aria-hidden="true" />}
                  label={
                    multiLangMode && multiLangs.length > 1
                      ? t('dub.generate_dub_multi', {
                          count: multiLangs.length,
                          defaultValue: 'Generate {{count}} dubs',
                        })
                      : t('dub.generate_dub')
                  }
                />
                {dubStep === 'done' && incrementalPlan && incrementalPlan.stale?.length > 0 && (
                  <FooterBtn
                    sm
                    tone="pink"
                    className="!h-[30px] !flex-none !px-[10px] enabled:hover:-translate-y-px enabled:active:translate-y-0 motion-reduce:transform-none [.shell-mini_&]:flex-1"
                    onClick={() =>
                      handleDubGenerate({ regenOnly: incrementalPlan.stale, preview: true })
                    }
                    icon={<Play className="fill-current" size={11} aria-hidden="true" />}
                    label={t('dub.regen_changed', { count: incrementalPlan.stale.length })}
                  />
                )}
              </>
            )}
            {dubStep === 'done' && (
              <FooterBtn
                sm
                tone="idle"
                className="dub-action-btn--verify !h-[30px] !flex-none !px-[9px] enabled:hover:-translate-y-px enabled:active:translate-y-0 motion-reduce:transform-none enabled:hover:shadow-[var(--shadow-sm)] [.shell-mini_&]:flex-1"
                disabled={qcRunning || !dubSegments.length}
                onClick={handleDubQc}
                icon={
                  qcRunning ? (
                    <Loader className="spinner" size={11} aria-hidden="true" />
                  ) : (
                    <ShieldCheck size={11} aria-hidden="true" />
                  )
                }
                label={t('dub.verify')}
                title={t('dub.qc_btn')}
                aria-label={t('dub.qc_btn')}
                aria-busy={qcRunning || undefined}
              />
            )}
            <FooterBtn
              sm
              tone={dubStep === 'done' ? 'green' : 'idle'}
              className="dub-action-btn--export !h-[30px] !flex-none !px-[10px] !font-semibold enabled:hover:-translate-y-px enabled:active:translate-y-0 motion-reduce:transform-none enabled:shadow-[0_5px_14px_color-mix(in_srgb,var(--chrome-severity-ok)_13%,transparent)] enabled:hover:shadow-[0_7px_18px_color-mix(in_srgb,var(--chrome-severity-ok)_20%,transparent)] [.shell-mini_&]:flex-1"
              disabled={dubStep !== 'done' && !dubSegments.length}
              onClick={() => setExportOpen(true)}
              icon={<Download size={12} aria-hidden="true" />}
              label={t('dub.export_btn')}
              title={t('dub.export_btn')}
              aria-label={t('dub.export_btn')}
            />
          </div>
        </div>
      </div>
      <DubPipelineStepper
        dubStep={dubStep}
        inline
        selectableSteps={pipelineSteps}
        onStepSelect={onPipelineStep}
      />
    </div>
  );
}
