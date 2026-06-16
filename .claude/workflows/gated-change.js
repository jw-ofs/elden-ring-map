export const meta = {
  name: 'gated-change',
  description: 'Run a gated source change through plan then independent adversarial review, writing the Agents/ artifacts the review gate expects',
  phases: [
    { title: 'Plan', detail: 'author the task doc + a line-level plan' },
    { title: 'Review', detail: 'a separate agent adversarially reviews and writes the review report' },
  ],
}

// args: { slug, title, problem, approach, files, root? }
// The runtime may hand `args` to the script as a JSON string rather than an object — parse if so.
const a = (function () {
  try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch (e) { return {} }
})()
const slug = a.slug || 'change'
const title = a.title || slug
const problem = a.problem || '(not provided)'
const approach = a.approach || '(not provided)'
const files = Array.isArray(a.files) ? a.files.join(', ') : (a.files || '(not provided)')

// Paths are relative to the project root. Run this with elden-ring-map as the project root and
// omit `root`. To run from a different project root, pass `root` (an absolute path to the repo).
const root = a.root ? (a.root.replace(/\\/g, '/').replace(/\/+$/, '') + '/') : ''
const taskPath = root + 'Agents/TODO/Active/' + slug + '.md'
const planPath = root + 'Agents/TODO/Active/' + slug + '-plan.md'
const reviewPath = root + 'Agents/Review-reports/' + slug + '-review.md'

const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { ok: { type: 'boolean' }, summary: { type: 'string' } },
  required: ['ok', 'summary'],
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['APPROVED', 'APPROVED_WITH_CHANGES', 'BLOCKED'] },
    reason: { type: 'string' },
  },
  required: ['verdict', 'reason'],
}

phase('Plan')
const plan = await agent(
  'You are PLANNING a gated source change in the Elden Ring map repo. All paths below are relative to the repo root.\n' +
  'Task slug: ' + slug + '\nTitle: ' + title + '\nProblem: ' + problem + '\nTarget files: ' + files + '\nProposed approach: ' + approach + '\n\n' +
  'Read the target files first so the plan is precise, then write TWO files with the Write tool:\n' +
  '1. ' + taskPath + ' — a task doc containing: a top-level heading with the title, a line that is exactly "## Status: Not Started", the problem statement with evidence, the hypotheses to prove or falsify, the key files, and a verification plan.\n' +
  '2. ' + planPath + ' — a LINE-LEVEL plan: for every code change cite the file path and line range, the verbatim current code, and the exact replacement code. For any data or config change, give the full new value. "Update X" is NOT an acceptable plan.\n' +
  'Return ok=true with a one-line summary once both files are written.',
  { label: 'plan:' + slug, phase: 'Plan', schema: PLAN_SCHEMA }
)

phase('Review')
const review = await agent(
  'You are an INDEPENDENT reviewer. You did NOT author this plan. Review it adversarially — your job is to find real problems before any code is written, not to rubber-stamp it.\n' +
  'Read ' + taskPath + ' and ' + planPath + ', plus the actual target files they reference.\n\n' +
  'Evaluate four dimensions, each as its own section: (1) logic errors and named edge cases, (2) variable-name / identifier consistency with connected systems, (3) data and schema alignment, (4) integration with related systems.\n\n' +
  'Write your review to ' + reviewPath + ' with the Write tool. The review MUST:\n' +
  '- reference the task filename "' + slug + '.md" verbatim somewhere in the body;\n' +
  '- contain at least 14 substantive (non-blank, non-heading) lines;\n' +
  '- include a section for each of the four dimensions above;\n' +
  '- end with a single final line that is exactly one of: "Verdict: APPROVED", "Verdict: APPROVED WITH CHANGES", or "Verdict: BLOCKED".\n\n' +
  'Be honest. If the plan is unsafe, wrong, or incomplete, choose BLOCKED and explain why. If small specific fixes are needed, choose APPROVED WITH CHANGES and enumerate them. Only choose APPROVED if you genuinely could not find a problem.\n' +
  'Return the verdict and a short reason.',
  { label: 'review:' + slug, phase: 'Review', schema: REVIEW_SCHEMA }
)

return {
  slug,
  plannerOk: plan ? plan.ok : false,
  verdict: review ? review.verdict : 'UNKNOWN',
  reason: review ? review.reason : '',
  artifacts: { task: taskPath, plan: planPath, review: reviewPath },
}
