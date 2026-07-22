---
name: cdms-crf-notebook
description: Generate and optionally execute CDMS CRF validation notebooks for the CDMS-Agent project. Use when the user asks to create a CRFRunner/gen_notebook Jupyter notebook for maven-crfs studies, inspect CRF plans or cases, regenerate versioned CDMS-Agent_test notebooks, or run generated notebooks with CDMSAgent against the local CDM Agent daemon.
---

<article>
  <h1>CDMS CRF Notebook Workflow</h1>

  <section>
    <h2>Purpose</h2>
    <p>
      Use this skill to generate CRF validation notebooks from
      <code>maven-crfs</code> TypeScript CRF source using the local
      <code>cdm-agent-client</code> package.
    </p>
    <p>
      Keep the responsibility boundary clear:
    </p>
    <ul>
      <li><code>CDMSAgent</code>: browser-control client connected to the CDM Agent daemon.</li>
      <li><code>CRFRunner</code>: loads CRF spec and builds a <code>CRFPlan</code>.</li>
      <li><code>CRFPlan</code>: grouped list of generated validation cases.</li>
      <li><code>CRFCase</code>: one validation flow made of <code>CDMSAgent</code> method calls and checks.</li>
      <li><code>CRFRun</code>: runs one case or a list of cases with <code>CDMSAgent</code>.</li>
      <li><code>gen_notebook</code>: writes the Jupyter Notebook workspace.</li>
      <li>Generated Notebook: human-operated workspace where browser actions are run and inspected.</li>
    </ul>
  </section>

  <section>
    <h2>Default Preset</h2>
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Value</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>agent_project_root</code></td>
          <td><code>C:\Users\SunbeomGwon\CDMS-Agent</code></td>
        </tr>
        <tr>
          <td><code>maven_root</code></td>
          <td><code>C:\Users\SunbeomGwon\maven-crfs</code></td>
        </tr>
        <tr>
          <td><code>study</code></td>
          <td><code>20260325_PRACTICE_GSB</code></td>
        </tr>
        <tr>
          <td><code>study_id</code></td>
          <td><code>PRACTICE_GSB</code></td>
        </tr>
        <tr>
          <td><code>visit_map</code></td>
          <td><code>{1: "V0", 2: "V1", 60: "V60"}</code></td>
        </tr>
        <tr>
          <td><code>notebook_dir</code></td>
          <td><code>C:\Users\SunbeomGwon\maven-crfs\src\crfs\20260325_PRACTICE_GSB</code></td>
        </tr>
        <tr>
          <td><code>notebook_name_pattern</code></td>
          <td><code>CDMS-Agent_test_v{version}.ipynb</code></td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>Generate a Versioned Notebook</h2>
    <p>
      When the user asks for a new version such as <code>v0.0.6</code>, create:
    </p>
    <pre><code>C:\Users\SunbeomGwon\maven-crfs\src\crfs\20260325_PRACTICE_GSB\CDMS-Agent_test_v0.0.6.ipynb</code></pre>
    <p>
      Run this PowerShell command from <code>C:\Users\SunbeomGwon\CDMS-Agent</code>.
      Request escalation because the output path is outside the workspace.
    </p>
    <pre><code>$env:PYTHONPATH='C:\Users\SunbeomGwon\CDMS-Agent\src'
python -c "from pathlib import Path; from cdm_agent_client.crf import CRFRunner, gen_notebook; maven=Path(r'C:\Users\SunbeomGwon\maven-crfs'); study='20260325_PRACTICE_GSB'; out=maven/'src'/'crfs'/study/'CDMS-Agent_test_v0.0.6.ipynb'; visit_map={1:'V0',2:'V1',60:'V60'}; runner=CRFRunner(maven_root=maven, study=study, visit_map=visit_map); runner.load_spec(); plan=runner.plan(); print('query_expected=', len(plan.query_expected)); print('no_query_expected=', len(plan.no_query_expected)); print('visibility=', len(plan.visibility)); print('availability=', len(plan.availability)); print('total=', len(plan.all)); path=gen_notebook(out, maven_root=maven, study=study, study_id='PRACTICE_GSB', agent_project_root=r'C:\Users\SunbeomGwon\CDMS-Agent', visit_map=visit_map); print('notebook=', path)"</code></pre>
  </section>

  <section>
    <h2>Expected Scenario Counts</h2>
    <p>
      For <code>20260325_PRACTICE_GSB</code>, the current expected counts are:
    </p>
    <ul>
      <li><code>query_expected</code>: <code>29</code></li>
      <li><code>no_query_expected</code>: <code>29</code></li>
      <li><code>visibility</code>: <code>15</code></li>
      <li><code>availability</code>: <code>135</code></li>
      <li><code>total</code>: <code>208</code></li>
    </ul>
    <p>
      If these counts change, report the new counts instead of forcing the old values.
    </p>
  </section>

  <section>
    <h2>Verify the Generated Notebook</h2>
    <pre><code>python -c "import json; p=r'C:\Users\SunbeomGwon\maven-crfs\src\crfs\20260325_PRACTICE_GSB\CDMS-Agent_test_v0.0.6.ipynb'; nb=json.load(open(p, encoding='utf-8')); print('cells=', len(nb.get('cells', []))); print('outputs=', sum(len(c.get('outputs', [])) for c in nb.get('cells', []) if c.get('cell_type')=='code')); print('uses_plan=', any('runner.plan' in ''.join(c.get('source', [])) for c in nb.get('cells', []))); print('uses_crfrun=', any('CRFRun' in ''.join(c.get('source', [])) for c in nb.get('cells', [])))"</code></pre>
    <p>
      A freshly generated notebook should usually have <code>outputs=0</code>.
      Do not claim that scenario results are saved unless cells were actually executed.
    </p>
  </section>

  <section>
    <h2>Execute the Notebook Only When Asked</h2>
    <p>
      Notebook generation and notebook execution are separate operations.
      If the user asks to execute and save outputs, first check daemon/browser connectivity:
    </p>
    <pre><code>$env:PYTHONPATH='C:\Users\SunbeomGwon\CDMS-Agent\src'
python -c "from cdm_agent_client import CDMSAgent; a=CDMSAgent(study_id='PRACTICE_GSB', stop_on_error=False); print('ping', a.ping()); s=a.inspect(); print('page', s.page_label); print('path', s.pathname)"</code></pre>
    <p>
      If <code>jupyter</code>, <code>nbclient</code>, or <code>nbformat</code> is unavailable,
      either ask before installing dependencies or use a minimal executor only if the user
      explicitly wants saved outputs.
    </p>
  </section>

  <section>
    <h2>Common User Requests</h2>
    <table>
      <thead>
        <tr>
          <th>User says</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>"Create notebook v0.0.6"</td>
          <td>Run <code>gen_notebook</code> with the default preset and verify file/cells.</td>
        </tr>
        <tr>
          <td>"Check the case list"</td>
          <td>Run <code>CRFRunner.load_spec()</code>, <code>plan()</code>, and print grouped counts or <code>plan.to_dataframe()</code>.</td>
        </tr>
        <tr>
          <td>"The notebook has no results"</td>
          <td>Explain that generation does not execute cells. Execute only if requested.</td>
        </tr>
        <tr>
          <td>"The extension is connected"</td>
          <td>Use <code>CDMSAgent.ping()</code> and <code>inspect()</code> before any browser-running workflow.</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>Validation Commands</h2>
    <pre><code>python -m compileall -f src\cdm_agent_client\crf</code></pre>
    <p>
      Use this after changing CRF code. It validates Python syntax only; it does not
      prove browser automation correctness.
    </p>
  </section>

  <section>
    <h2>Important Notes</h2>
    <ul>
      <li>Prefer <code>gen_notebook</code> for new code.</li>
      <li><code>generate_crf_notebook</code> is a compatibility alias.</li>
      <li>Do not edit unrelated extension, notebook, or package files unless the user asks.</li>
      <li>When writing outside <code>C:\Users\SunbeomGwon\CDMS-Agent</code>, request filesystem escalation.</li>
      <li>Do not confuse "created notebook" with "executed notebook". State which one happened.</li>
    </ul>
  </section>
</article>
