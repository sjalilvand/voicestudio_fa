import { expect, it } from 'vitest';
import {
  addWorkflowStep,
  connectWorkflowSteps,
  duplicateWorkflowName,
  makeCallWorkflow,
  makeWorkflow,
  parseWorkflowLibrary,
  repairWorkflowName,
  removeWorkflowStep,
} from './workflow-model';

it('creates a connected, editable call template without a destination number', () => {
  const document = makeCallWorkflow('Book a restaurant', 'Book a table for two');
  expect(document.steps.map((step) => step.kind)).toEqual(['start', 'call', 'end']);
  expect(document.steps[1].text).toBe('Book a table for two');
  expect(document.steps[1].phone).toBe('');
  expect(document.connections.map((edge) => [edge.source, edge.target])).toEqual([
    [document.steps[0].id, document.steps[1].id],
    [document.steps[1].id, document.steps[2].id],
  ]);
});

it('keeps a usable workflow after reopening saved canvas data', () => {
  const document = addWorkflowStep(makeWorkflow('Reception'), 'call');
  const linked = connectWorkflowSteps(document, document.steps[1].id, document.steps[3].id);
  const saved = JSON.stringify({ version: 1, activeId: linked.id, documents: [linked] });
  const loaded = parseWorkflowLibrary(saved, 'Untitled');
  expect(loaded.activeId).toBe(linked.id);
  expect(loaded.documents[0].steps).toHaveLength(4);
  expect(loaded.documents[0].connections).toHaveLength(3);
});

it('ignores broken saved edges and removes a step with all connected edges', () => {
  const document = makeWorkflow('Reception');
  const saved = JSON.stringify({
    version: 1,
    activeId: document.id,
    documents: [{
      ...document,
      connections: [
        ...document.connections,
        { id: 'broken', source: document.steps[0].id, target: 'missing' },
      ],
    }],
  });
  const loaded = parseWorkflowLibrary(saved, 'Untitled').documents[0];
  expect(loaded.connections).toHaveLength(2);
  const withoutAgent = removeWorkflowStep(loaded, document.steps[1].id);
  expect(withoutAgent.steps).toHaveLength(2);
  expect(withoutAgent.connections).toHaveLength(0);
  expect(connectWorkflowSteps(loaded, document.steps[0].id, document.steps[0].id)).toBe(loaded);
});

it('repairs a saved untranslated default name without changing custom names', () => {
  const broken = makeWorkflow('workflows.untitled');
  const custom = makeWorkflow('Reception');
  const saved = JSON.stringify({
    version: 1,
    activeId: broken.id,
    documents: [broken, custom],
  });
  const loaded = parseWorkflowLibrary(saved, 'Untitled workflow');
  expect(loaded.documents.map((document) => document.name)).toEqual([
    'Untitled workflow',
    'Reception',
  ]);
});

it('localizes an automatically named workflow when the app language changes', () => {
  const autoNamed = makeWorkflow('Untitled workflow', true);
  const custom = makeWorkflow('Reception');
  const saved = JSON.stringify({
    version: 1,
    activeId: autoNamed.id,
    documents: [autoNamed, custom],
  });
  const loaded = parseWorkflowLibrary(saved, 'Unbenannter Workflow');
  expect(loaded.documents.map((document) => document.name)).toEqual([
    'Unbenannter Workflow',
    'Reception',
  ]);
});

it('repairs copied legacy keys and numbers new copies without compounding names', () => {
  expect(repairWorkflowName('workflows.untitled copy copy copy', 'Untitled workflow')).toBe(
    'Untitled workflow (4)',
  );
  const documents = [
    makeWorkflow('Untitled workflow'),
    makeWorkflow('Untitled workflow (2)'),
    makeWorkflow('Untitled workflow (3)'),
  ];
  expect(duplicateWorkflowName('Untitled workflow (3)', documents)).toBe('Untitled workflow (4)');
});
