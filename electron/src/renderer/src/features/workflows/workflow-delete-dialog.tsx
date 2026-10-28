import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
// CLEAN-ROOM (spec W11-residue §E25): imports: Trash2Icon, Button, Dialog parts, describeError, deleteWorkflowRun

/** Confirms deleting a workflow; its saved run is removed before the draft is. */
export function WorkflowDeleteDialog({
  workflow,
  onCancel,
  onDeleted,
}: {
  workflow: { id: string; name: string } | null;
  onCancel(): void;
  onDeleted(id: string): void;
}) {
  const { t } = useTranslation();
  const cancel = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const id = workflow?.id;
  useEffect(() => setError(''), [id]);
  const confirm = async () => {
    if (!id || busy) return;
    setBusy(true);
    setError('');
    try {
      await deleteWorkflowRun(id);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
      return;
    }
    setBusy(false);
    onDeleted(id);
  };
  return (
    <Dialog
      open={workflow !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent
        showCloseButton={false}
        initialFocus={cancel}
        style={{ background: 'var(--popover)' }}
      >
        <DialogHeader>
          <DialogTitle>{t('workflows.delete')}</DialogTitle>
          <DialogDescription>
            {t('workflows.delete_confirm', { name: workflow?.name ?? '' })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
          <Button ref={cancel} variant="outline" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button variant="destructive" disabled={busy} onClick={() => void confirm()}>
            <Trash2Icon aria-hidden="true" />
            {t('common.delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
