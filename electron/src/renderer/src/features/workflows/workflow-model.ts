export const WORKFLOW_STORAGE_KEY = 'voicestudio.workflows.v1';

export type StepKind = 'start' | 'agent' | 'speak' | 'condition' | 'call' | 'end';
export const STEP_KINDS: StepKind[] = ['start', 'agent', 'speak', 'condition', 'call', 'end'];

export interface WorkflowStep {
  id: string;
  kind: StepKind;
  position: { x: number; y: number };
  title: string;
  text: string;
  phone: string;
}

export interface WorkflowConnection {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
}

export interface WorkflowDocument {
  id: string;
  name: string;
  autoNamed?: boolean;
  updatedAt: number;
  steps: WorkflowStep[];
  connections: WorkflowConnection[];
}

export interface WorkflowLibrary {
  version: 1;
  activeId: string;
  documents: WorkflowDocument[];
}

export function repairWorkflowName(name: string, untitled: string): string {
  if (!/^(?:workflows\.untitled|Untitled workflow)(?: copy)*$/.test(name)) return name;
  const copies = name.match(/\bcopy\b/g)?.length ?? 0;
  return copies ? `${untitled} (${copies + 1})` : untitled;
}

export function duplicateWorkflowName(name: string, documents: WorkflowDocument[]): string {
  const base = name.replace(/ \(\d+\)$/, '');
  const names = new Set(documents.map((document) => document.name));
  let number = 2;
  while (names.has(`${base} (${number})`)) number += 1;
  return `${base} (${number})`;
}

export function makeStep(kind: StepKind, position: { x: number; y: number }): WorkflowStep {
  return { id: crypto.randomUUID(), kind, position, title: '', text: '', phone: '' };
}

export function makeWorkflow(name: string, autoNamed = false): WorkflowDocument {
  const start = makeStep('start', { x: 40, y: 80 });
  const agent = makeStep('agent', { x: 315, y: 80 });
  const end = makeStep('end', { x: 590, y: 80 });
  return {
    id: crypto.randomUUID(),
    name,
    autoNamed,
    updatedAt: Date.now(),
    steps: [start, agent, end],
    connections: [
      { id: crypto.randomUUID(), source: start.id, target: agent.id },
      { id: crypto.randomUUID(), source: agent.id, target: end.id },
    ],
  };
}

/** A ready-to-edit call draft; the graph itself never dials or executes steps. */
export function makeCallWorkflow(name: string, brief: string): WorkflowDocument {
  const document = makeWorkflow(name);
  return {
    ...document,
    steps: document.steps.map((step) => step.kind === 'agent'
      ? { ...step, kind: 'call' as const, title: name, text: brief }
      : step),
  };
}

/** Treat saved canvas data as untrusted; never let malformed storage break the workspace. */
export function parseWorkflowLibrary(raw: string | null, untitled: string): WorkflowLibrary {
  try {
    const value = JSON.parse(raw ?? 'null');
    if (value?.version === 1 && Array.isArray(value.documents)) {
      const documents: WorkflowDocument[] = value.documents.slice(0, 100).flatMap((candidate: unknown) => {
        if (!candidate || typeof candidate !== 'object') return [];
        const item = candidate as Record<string, unknown>;
        if (typeof item.id !== 'string' || typeof item.name !== 'string' || !Array.isArray(item.steps))
          return [];
        const steps = item.steps.slice(0, 300).flatMap((candidateStep: unknown): WorkflowStep[] => {
          if (!candidateStep || typeof candidateStep !== 'object') return [];
          const step = candidateStep as Record<string, unknown>;
          const position = step.position as Record<string, unknown> | undefined;
          if (
            typeof step.id !== 'string' ||
            !STEP_KINDS.includes(step.kind as StepKind) ||
            !position ||
            !Number.isFinite(position.x) ||
            !Number.isFinite(position.y)
          )
            return [];
          return [{
            id: step.id,
            kind: step.kind as StepKind,
            position: { x: position.x as number, y: position.y as number },
            title: typeof step.title === 'string' ? step.title.slice(0, 120) : '',
            text: typeof step.text === 'string' ? step.text.slice(0, 20_000) : '',
            phone: typeof step.phone === 'string' ? step.phone.slice(0, 80) : '',
          }];
        });
        const ids = new Set(steps.map((step) => step.id));
        const connections = (Array.isArray(item.connections) ? item.connections : [])
          .slice(0, 600)
          .flatMap((candidateEdge: unknown): WorkflowConnection[] => {
            if (!candidateEdge || typeof candidateEdge !== 'object') return [];
            const edge = candidateEdge as Record<string, unknown>;
            if (
              typeof edge.id !== 'string' ||
              typeof edge.source !== 'string' ||
              typeof edge.target !== 'string' ||
              !ids.has(edge.source) ||
              !ids.has(edge.target) ||
              edge.source === edge.target
            )
              return [];
            return [{
              id: edge.id,
              source: edge.source,
              target: edge.target,
              sourceHandle: typeof edge.sourceHandle === 'string' ? edge.sourceHandle : undefined,
            }];
          });
        return [{
          id: item.id,
          // Early builds could save a translation key, including in copy names.
          name: item.autoNamed === true
            ? untitled
            : repairWorkflowName(item.name.slice(0, 120), untitled) || untitled,
          autoNamed: item.autoNamed === true ||
            item.name === 'workflows.untitled' || item.name === 'Untitled workflow',
          updatedAt: typeof item.updatedAt === 'number' ? item.updatedAt : Date.now(),
          steps,
          connections,
        }];
      });
      if (documents.length) {
        return {
          version: 1,
          activeId: documents.some((document) => document.id === value.activeId)
            ? value.activeId
            : documents[0].id,
          documents,
        };
      }
    }
  } catch {
    // An unreadable draft must not prevent creating a new workflow.
  }
  const first = makeWorkflow(untitled, true);
  return { version: 1, activeId: first.id, documents: [first] };
}

export function addWorkflowStep(document: WorkflowDocument, kind: StepKind): WorkflowDocument {
  const index = document.steps.length;
  const step = makeStep(kind, {
    x: 40 + (index % 3) * 275,
    y: 80 + Math.floor(index / 3) * 155,
  });
  return { ...document, steps: [...document.steps, step], updatedAt: Date.now() };
}

export function connectWorkflowSteps(
  document: WorkflowDocument,
  source: string,
  target: string,
  sourceHandle?: string,
): WorkflowDocument {
  if (
    source === target ||
    !document.steps.some((step) => step.id === source) ||
    !document.steps.some((step) => step.id === target) ||
    document.connections.some(
      (edge) => edge.source === source && edge.target === target && edge.sourceHandle === sourceHandle,
    )
  )
    return document;
  return {
    ...document,
    updatedAt: Date.now(),
    connections: [...document.connections, { id: crypto.randomUUID(), source, target, sourceHandle }],
  };
}

export function removeWorkflowStep(document: WorkflowDocument, id: string): WorkflowDocument {
  return {
    ...document,
    updatedAt: Date.now(),
    steps: document.steps.filter((step) => step.id !== id),
    connections: document.connections.filter((edge) => edge.source !== id && edge.target !== id),
  };
}
