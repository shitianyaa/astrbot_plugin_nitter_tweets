"""Verify the inline demo preserves drafts and cannot write through the bridge."""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_wizard_demo_isolates_drafts_and_blocks_writes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for dashboard behavior checks")
    wizard = (ROOT / "pages/dashboard/wizard.js").read_text(encoding="utf-8")
    core = (ROOT / "pages/dashboard/core.js").read_text(encoding="utf-8")
    api = core[
        core.index("function apiResult") : core.index(
            "/* ===", core.index("async function apiPost")
        )
    ]
    harness = r"""
const assert = require('node:assert/strict');
const cls = {add(){}, remove(){}, toggle(){}};
const document = {body: {classList:cls}, activeElement:{focus(){}}};
const window = {scrollTo(){}};
function element() {return {hidden:true, replaceChildren(){}, querySelector(){return null;}};}
const els = {wizardBar:element(), wizardReview:element(), wizardStartBtn:element()};
const state = {config:{groups:[]}, configError:false, groups:[], groupDrafts:{},
 configDraft:{translate_enabled:true}, pendingBlacklists:{}, selectedGroupId:'',
 configSearch:'old search', configActive:'media', configSearchPinned:true,
 targetProbeResults:{}, targetBlacklists:[], view:'overview'};
const items = {translate_enabled:{key:'translate_enabled', value:false},
 instances:{key:'instances',value:[]}, check_interval_minutes:{value:30}};
const configDirtyKeys = new Set(['translate_enabled']);
let sheetOpen=false, cmdkOpen=false;
let posts=0;
const bridge = {apiPost:async()=>{posts++; return {success:true};}};
function h(){return {};}
function showAlert(){}
function findConfigItem(key){return items[key];}
function switchView(view){state.view=view;}
function renderConfig(){}
function renderGroupCards(){}
function closeCreateGroupModal(){}
function closeSheet(){sheetOpen=false;}
function openGroupSheet(){sheetOpen=true;}
function snapshotGroup(group){return structuredClone(group);}
function buildConfigIndex(){}
function markData(){}
function openConfirm(options){options.action();}
"""
    scenarios = r"""
(async()=>{
 const original=structuredClone(state);
 startWizard();
 assert.equal(state.view,'config');
 state.configDraft.instances=['http://nitter:8080'];
 configDirtyKeys.add('instances');
 goWizardStep(1,true);
 assert.equal(wizard.skipped.has(0),true);
 goWizardStep(0);
 assert.equal(wizard.skipped.has(0),true);
 assert.deepEqual(state.configDraft.instances,['http://nitter:8080']);
 goWizardStep(5);
 wizardCreateGroup('Preview','blogger');
 assert.equal(posts,0);
 assert.equal(state.groups.length,1);
 const draft=state.groupDrafts[state.selectedGroupId];
 draft.watch_users=['nasa'];
 assert.equal(draft.enabled,false);
 assert.deepEqual(draft.push_targets,[]);
 goWizardStep(6);
 const changes=wizardChanges();
 assert.equal(changes.config.length,1); // Existing draft is not a new change.
 assert.equal(changes.groups.length,1);
 await assert.rejects(apiPost('web/config/save',{}),/Demo/);
 await assert.rejects(apiPost('web/groups/create',{}),/Demo/);
 await assert.rejects(apiPost('web/seen/clear',{}),/Demo/);
 assert.equal(posts,0);
 exitWizard();
 assert.equal(wizardActive(),false);
 for(const key of Object.keys(original)) assert.deepEqual(state[key],original[key],key);
 startWizard();
 assert.equal(wizardChanges().config.length,0);
 state.configDraft.translate_enabled=false;
 configDirtyKeys.delete('translate_enabled');
 assert.equal(wizardChanges().config.length,1); // Reverting a pre-existing draft is a change.
 exitWizard();
 await apiPost('web/config/save',{});
 assert.equal(posts,1); // Normal page writes still work after the demo.
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node],
        input=harness + wizard + api + scenarios,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
