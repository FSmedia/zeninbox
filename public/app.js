// ZenInbox Application Controller
let currentFilter = 'all';
let searchDebounceTimer = null;
let isScanning = false;
let scanPollInterval = null;

// Rapid Triage State
let triageSenders = [];
let currentTriageIndex = 0;

document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();
    loadDashboardStats();
    loadActivityLogs();
    loadQuarantineQueue();
    loadAIRecommendations();
    checkScanStatus();

    // Keyboard navigation for Rapid Triage
    document.addEventListener('keydown', (e) => {
        const triageTab = document.getElementById('tab-triage');
        if (triageTab && !triageTab.classList.contains('hidden')) {
            if (e.key === '1') triageAction('keep');
            if (e.key === '2') triageAction('keep_newest_only');
            if (e.key === '3') triageAction('rollup');
            if (e.key === '4') triageAction('unsubscribe_and_delete');
        }
    });
});

// Toast Notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    const colorClass = type === 'success' 
        ? 'bg-emerald-600 text-white' 
        : type === 'error' 
        ? 'bg-rose-600 text-white' 
        : 'bg-indigo-600 text-white';

    toast.className = `flex items-center space-x-2 px-4 py-3 rounded-xl shadow-xl text-xs font-medium transition-all duration-300 transform translate-y-2 opacity-0 ${colorClass}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
    }, 10);

    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Tab Switching
function switchTab(tabName) {
    const tabs = ['overview', 'ai', 'triage', 'subscriptions', 'screening', 'digest', 'rules', 'settings'];
    tabs.forEach(t => {
        const el = document.getElementById(`tab-${t}`);
        const btn = document.getElementById(`tab-btn-${t}`);
        if (el) el.classList.add('hidden');
        if (btn) {
            btn.classList.remove('tab-active');
            btn.classList.add('text-slate-400');
        }
    });

    const activeEl = document.getElementById(`tab-${tabName}`);
    const activeBtn = document.getElementById(`tab-btn-${tabName}`);
    if (activeEl) activeEl.classList.remove('hidden');
    if (activeBtn) {
        activeBtn.classList.add('tab-active');
        activeBtn.classList.remove('text-slate-400');
    }

    if (tabName === 'overview') {
        loadDashboardStats();
        loadActivityLogs();
        loadQuarantineQueue();
        loadAIRecommendations();
    } else if (tabName === 'ai') {
        loadAIRecommendations();
    } else if (tabName === 'triage') {
        startRapidTriage();
    } else if (tabName === 'subscriptions') {
        loadSubscriptions();
    } else if (tabName === 'screening') {
        loadQuarantineQueue();
    } else if (tabName === 'digest') {
        loadRollupItems();
    } else if (tabName === 'rules') {
        loadRules();
    } else if (tabName === 'settings') {
        loadSettings();
    }

    lucide.createIcons();
}

// 1. Dashboard Stats
async function loadDashboardStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        document.getElementById('overviewScore').innerText = `${data.health_score || 85}%`;
        document.getElementById('overviewScoreBar').style.width = `${data.health_score || 85}%`;
        document.getElementById('healthScoreBadge').innerText = `${data.health_score || 85}%`;

        document.getElementById('overviewQuarantine').innerText = data.pending_quarantine || 0;
        document.getElementById('quarantineCountBadge').innerText = data.pending_quarantine || 0;

        document.getElementById('overviewSubs').innerText = data.total_subscriptions || data.total_senders || 0;
        document.getElementById('subCountBadge').innerText = data.total_subscriptions || data.total_senders || 0;

        const totalDigestAndFresh = (data.total_rollups || 0) + (data.total_kept_newest || 0);
        document.getElementById('overviewRollups').innerText = totalDigestAndFresh;
        document.getElementById('rollupCountBadge').innerText = data.total_rollups || 0;

        document.getElementById('co2Stat').innerText = `${data.co2_saved_grams || 0}g CO2 saved`;
    } catch (e) {
        console.error('Stats error:', e);
    }
}

async function loadActivityLogs() {
    try {
        const res = await fetch('/api/activity');
        const data = await res.json();
        const container = document.getElementById('overviewActivityLogs');
        if (!data.logs || data.logs.length === 0) {
            container.innerHTML = '<p class="text-slate-500 text-center py-4">No recent activity.</p>';
            return;
        }

        container.innerHTML = data.logs.map(log => {
            const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
            return `
                <div class="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80 flex items-start space-x-2.5">
                    <div class="w-2 h-2 rounded-full bg-indigo-500 mt-1.5 flex-shrink-0"></div>
                    <div class="flex-1 min-w-0">
                        <p class="text-slate-300 leading-tight">${log.details}</p>
                        <span class="text-[10px] text-slate-500">${time} &bull; ${log.action_type}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Activity logs error:', e);
    }
}

// 2. AI Inbox Advisor
async function loadAIRecommendations() {
    try {
        const res = await fetch('/api/ai/recommendations');
        const data = await res.json();
        const recs = data.recommendations || [];

        // Update badges
        document.getElementById('aiRecsCountBadge').innerText = recs.length;
        document.getElementById('aiBannerCount').innerText = `${recs.length} Actions`;

        const grid = document.getElementById('aiRecommendationsGrid');
        if (recs.length === 0) {
            grid.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <i data-lucide="check-circle" class="w-12 h-12 text-emerald-400 mx-auto mb-3 opacity-70"></i>
                    <p class="text-slate-300 font-medium text-sm">Inbox is Fully Optimized</p>
                    <p class="text-slate-500 text-xs mt-1">AI found no urgent backlog or stale subscriptions to clean.</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }

        grid.innerHTML = recs.map(r => {
            let badgeBg = 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20';
            let btnBg = 'bg-indigo-600 hover:bg-indigo-500 text-white';

            if (r.action === 'unsubscribe_and_delete') {
                badgeBg = 'bg-rose-500/10 text-rose-400 border-rose-500/20';
                btnBg = 'bg-rose-600 hover:bg-rose-500 text-white';
            } else if (r.action === 'keep_newest_only') {
                badgeBg = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
                btnBg = 'bg-amber-600 hover:bg-amber-500 text-white';
            } else if (r.action === 'vip_whitelist') {
                badgeBg = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
                btnBg = 'bg-emerald-600 hover:bg-emerald-500 text-white';
            } else if (r.action === 'rollup') {
                badgeBg = 'bg-purple-500/10 text-purple-400 border-purple-500/20';
                btnBg = 'bg-purple-600 hover:bg-purple-500 text-white';
            }

            return `
                <div class="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-3 flex flex-col justify-between hover:border-slate-700 transition">
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full border ${badgeBg}">${r.category}</span>
                            <span class="text-xs font-bold text-emerald-400">${r.confidence}% Confidence</span>
                        </div>
                        <h4 class="text-sm font-semibold text-slate-100 truncate">${r.name || r.email}</h4>
                        <div class="text-[11px] text-slate-500 truncate mb-2">&lt;${r.email}&gt;</div>
                        <p class="text-xs text-slate-300 leading-relaxed">${r.reason}</p>
                    </div>

                    <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between">
                        <span class="text-xs text-slate-400">${r.total_emails} emails in inbox</span>
                        <button onclick="executeAISingle('${r.email}', '${r.action}')" class="px-3 py-1.5 rounded-lg text-xs font-semibold ${btnBg} transition shadow-sm">
                            ${r.action_label}
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        lucide.createIcons();
    } catch (e) {
        console.error('AI Recommendations error:', e);
    }
}

async function executeAISingle(email, action) {
    try {
        const res = await fetch('/api/ai/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, action: action })
        });
        const data = await res.json();
        showToast(`AI Action applied: ${action} for ${email}`, 'success');
        loadAIRecommendations();
        loadDashboardStats();
    } catch (e) {
        showToast('Error applying AI recommendation', 'error');
    }
}

async function executeAllAIRecommendations() {
    if (!confirm('Apply all high-confidence AI actions across your inbox? This will purge inactive subscriptions and keep newest editions of frequent newsletters.')) {
        return;
    }
    try {
        showToast('Applying high-confidence AI recommendations...', 'info');
        const res = await fetch('/api/ai/execute-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ min_confidence: 80 })
        });
        const data = await res.json();
        showToast(`AI successfully applied ${data.total_applied} automated actions!`, 'success');
        loadAIRecommendations();
        loadDashboardStats();
        loadSubscriptions();
    } catch (e) {
        showToast('Error executing AI recommendations', 'error');
    }
}

// 3. Rapid Triage (Flash Review Mode)
async function startRapidTriage() {
    try {
        const res = await fetch('/api/subscriptions?filter=subscription&sort=clutter_desc');
        const data = await res.json();
        triageSenders = (data.senders || []).filter(s => s.action_preference !== 'unsubscribe_and_delete');
        currentTriageIndex = 0;
        renderTriageCard();
    } catch (e) {
        console.error('Triage start error:', e);
    }
}

function renderTriageCard() {
    const container = document.getElementById('triageCardContainer');
    if (!triageSenders || triageSenders.length === 0 || currentTriageIndex >= triageSenders.length) {
        container.innerHTML = `
            <div class="py-12 space-y-3">
                <i data-lucide="check-circle-2" class="w-16 h-16 text-emerald-400 mx-auto"></i>
                <h3 class="text-lg font-bold text-white">All Subscriptions Triaged!</h3>
                <p class="text-xs text-slate-400">Your inbox is streamlined and purified.</p>
                <button onclick="switchTab('overview')" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold">
                    Return to Overview
                </button>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    const s = triageSenders[currentTriageIndex];
    const openRatePct = Math.round((s.open_rate || 0) * 100);

    container.innerHTML = `
        <div class="space-y-4">
            <div class="text-xs text-slate-500 uppercase tracking-widest font-semibold">
                Sender ${currentTriageIndex + 1} of ${triageSenders.length}
            </div>

            <div class="w-16 h-16 rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center mx-auto text-xl font-bold text-white shadow-lg">
                ${(s.name || s.email)[0].toUpperCase()}
            </div>

            <div>
                <h3 class="text-lg font-bold text-white">${s.name || s.email}</h3>
                <p class="text-xs text-slate-400">&lt;${s.email}&gt;</p>
            </div>

            <div class="flex items-center justify-center space-x-6 py-2 text-xs">
                <div class="text-center">
                    <span class="block text-xl font-extrabold text-white">${s.total_received}</span>
                    <span class="text-slate-400">Total Emails</span>
                </div>
                <div class="h-8 w-px bg-slate-800"></div>
                <div class="text-center">
                    <span class="block text-xl font-extrabold ${openRatePct > 50 ? 'text-emerald-400' : 'text-amber-400'}">${openRatePct}%</span>
                    <span class="text-slate-400">Open Rate</span>
                </div>
            </div>

            <!-- 4 Instant Action Buttons -->
            <div class="grid grid-cols-2 gap-3 pt-2">
                <button onclick="triageAction('keep')" class="p-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center justify-center space-x-2 border border-slate-700 transition">
                    <span class="w-5 h-5 rounded-full bg-slate-700 flex items-center justify-center text-[10px] text-slate-300 font-bold">1</span>
                    <span>Keep in Inbox</span>
                </button>

                <button onclick="triageAction('keep_newest_only')" class="p-3 rounded-xl bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 text-xs font-semibold flex items-center justify-center space-x-2 border border-amber-500/30 transition">
                    <span class="w-5 h-5 rounded-full bg-amber-500/30 flex items-center justify-center text-[10px] text-amber-300 font-bold">2</span>
                    <span>Keep Newest Only</span>
                </button>

                <button onclick="triageAction('rollup')" class="p-3 rounded-xl bg-purple-600/20 hover:bg-purple-600/30 text-purple-300 text-xs font-semibold flex items-center justify-center space-x-2 border border-purple-500/30 transition">
                    <span class="w-5 h-5 rounded-full bg-purple-500/30 flex items-center justify-center text-[10px] text-purple-300 font-bold">3</span>
                    <span>Daily Digest</span>
                </button>

                <button onclick="triageAction('unsubscribe_and_delete')" class="p-3 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 text-xs font-semibold flex items-center justify-center space-x-2 border border-rose-500/30 transition">
                    <span class="w-5 h-5 rounded-full bg-rose-500/30 flex items-center justify-center text-[10px] text-rose-300 font-bold">4</span>
                    <span>Unsubscribe & Trash</span>
                </button>
            </div>
        </div>
    `;
    lucide.createIcons();
}

async function triageAction(action) {
    if (currentTriageIndex >= triageSenders.length) return;
    const s = triageSenders[currentTriageIndex];
    currentTriageIndex++;
    renderTriageCard();

    // Execute in background
    try {
        await fetch('/api/subscriptions/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ emails: [s.email], action: action })
        });
        loadDashboardStats();
    } catch (e) {
        console.error('Triage action error:', e);
    }
}

// 4. Subscriptions Manager & Cleaner
async function loadSubscriptions() {
    const search = document.getElementById('subSearchInput').value;
    const url = `/api/subscriptions?filter=${currentFilter}&search=${encodeURIComponent(search)}`;
    try {
        const res = await fetch(url);
        const data = await res.json();
        const senders = data.senders || [];
        const tableBody = document.getElementById('subscriptionsTableBody');

        if (senders.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="5" class="py-12 text-center text-slate-500 text-xs">
                        No senders found for this filter.
                    </td>
                </tr>
            `;
            return;
        }

        tableBody.innerHTML = senders.map(s => {
            const openRatePct = Math.round((s.open_rate || 0) * 100);
            const openRateColor = openRatePct >= 50 ? 'text-emerald-400' : (openRatePct >= 20 ? 'text-amber-400' : 'text-rose-400');
            const openRateBarColor = openRatePct >= 50 ? 'bg-emerald-500' : (openRatePct >= 20 ? 'bg-amber-500' : 'bg-rose-500');

            let unsubBadge = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-500">Auto-Trash</span>';
            if (s.unsubscribe_url) {
                unsubBadge = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">1-Click RFC</span>';
            } else if (s.unsubscribe_mailto) {
                unsubBadge = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">Mailto RFC</span>';
            }

            let statusPill = '';
            if (s.action_preference === 'keep_newest_only') {
                statusPill = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 ml-2">Kept Newest Only</span>';
            } else if (s.action_preference === 'rollup') {
                statusPill = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 ml-2">In Daily Digest</span>';
            } else if (s.action_preference === 'unsubscribe_and_delete') {
                statusPill = '<span class="text-[10px] px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 ml-2">Unsubscribed</span>';
            }

            return `
                <tr class="hover:bg-slate-800/20 transition">
                    <td class="py-3 px-4">
                        <div class="flex items-center space-x-2">
                            <span class="font-medium text-slate-200 text-xs">${s.name || s.email}</span>
                            ${statusPill}
                        </div>
                        <div class="text-[11px] text-slate-500">${s.email}</div>
                    </td>
                    <td class="py-3 px-4 text-center font-semibold text-xs text-slate-300">${s.total_received}</td>
                    <td class="py-3 px-4">
                        <div class="flex items-center space-x-2">
                            <span class="text-xs font-semibold ${openRateColor} w-8">${openRatePct}%</span>
                            <div class="w-16 bg-slate-800 h-1.5 rounded-full overflow-hidden">
                                <div class="${openRateBarColor} h-full rounded-full" style="width: ${openRatePct}%"></div>
                            </div>
                        </div>
                    </td>
                    <td class="py-3 px-4 text-center">${unsubBadge}</td>
                    <td class="py-3 px-4 text-right whitespace-nowrap space-x-1">
                        <!-- Keep in Inbox -->
                        <button onclick="cleanerAction('${s.email}', 'keep')" title="Keep in Inbox" class="p-1.5 rounded-lg ${s.action_preference === 'keep' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-emerald-400'} transition">
                            <i data-lucide="inbox" class="w-4 h-4"></i>
                        </button>
                        <!-- Keep Newest Only -->
                        <button onclick="cleanerAction('${s.email}', 'keep_newest_only')" title="Keep Newest Edition Only (Prunes older backlogged issues to trash)" class="p-1.5 rounded-lg ${s.action_preference === 'keep_newest_only' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-amber-400'} transition">
                            <i data-lucide="sparkles" class="w-4 h-4"></i>
                        </button>
                        <!-- Daily Digest -->
                        <button onclick="cleanerAction('${s.email}', 'rollup')" title="Add to Daily Digest" class="p-1.5 rounded-lg ${s.action_preference === 'rollup' ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-purple-400'} transition">
                            <i data-lucide="layers" class="w-4 h-4"></i>
                        </button>
                        <!-- Unsubscribe & Purge -->
                        <button onclick="cleanerAction('${s.email}', 'unsubscribe_and_delete')" title="Unsubscribe + Delete All Past Messages" class="p-1.5 rounded-lg ${s.action_preference === 'unsubscribe_and_delete' ? 'bg-rose-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-rose-400'} transition">
                            <i data-lucide="trash-2" class="w-4 h-4"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
        lucide.createIcons();
    } catch (e) {
        console.error('Subscriptions error:', e);
    }
}

function setSubFilter(filterName) {
    currentFilter = filterName;
    ['all', 'subscription', 'keep_newest', 'low_open_rate', 'rollup', 'unsubscribed'].forEach(f => {
        const btn = document.getElementById(`subFilter-${f}`);
        if (btn) {
            if (f === filterName) {
                btn.className = 'px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white';
            } else {
                btn.className = 'px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-400 hover:text-white';
            }
        }
    });
    loadSubscriptions();
}

function debounceSubSearch() {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(loadSubscriptions, 300);
}

async function cleanerAction(email, action) {
    try {
        const res = await fetch('/api/subscriptions/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ emails: [email], action: action })
        });
        const data = await res.json();
        if (action === 'keep_newest_only') {
            showToast(`Kept newest edition of ${email}; older issues purged to Trash.`, 'success');
        } else if (action === 'unsubscribe_and_delete') {
            showToast(`Unsubscribed & deleted emails for ${email}`, 'success');
        } else if (action === 'rollup') {
            showToast(`Added ${email} to Daily Digest`, 'info');
        } else {
            showToast(`Restored ${email} to Inbox`, 'info');
        }
        loadSubscriptions();
        loadDashboardStats();
    } catch (e) {
        showToast('Error performing action', 'error');
    }
}

async function pruneAllSubscriptionsToNewest() {
    if (!confirm('Keep Newest Edition Only: Prune older backlogged editions across ALL active subscriptions while keeping the single freshest issue of each?')) {
        return;
    }
    try {
        showToast('Pruning older editions across all subscriptions...', 'info');
        const res = await fetch('/api/subscriptions/prune-all-newest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keep_count: 1 })
        });
        const data = await res.json();
        showToast(`Purged ${data.total_older_emails_pruned} older issues across ${data.senders_processed} subscriptions!`, 'success');
        loadSubscriptions();
        loadDashboardStats();
    } catch (e) {
        showToast('Error pruning older editions', 'error');
    }
}

async function bulkCleanInactive() {
    if (!confirm('Are you sure you want to unsubscribe and delete all past messages from senders with < 15% open rate?')) {
        return;
    }
    try {
        const res = await fetch('/api/subscriptions/bulk-clean', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_open_rate: 0.15, min_emails: 2 })
        });
        const data = await res.json();
        showToast(`Cleaned & unsubscribed ${data.total_cleaned} inactive newsletters!`, 'success');
        loadSubscriptions();
        loadDashboardStats();
    } catch (e) {
        showToast('Error running bulk clean', 'error');
    }
}

// 5. Screening Room (Gatekeeper Quarantine)
async function loadQuarantineQueue() {
    try {
        const res = await fetch('/api/gatekeeper/quarantine');
        const data = await res.json();
        const items = data.items || [];

        const overviewContainer = document.getElementById('overviewQuarantineList');
        if (items.length === 0) {
            overviewContainer.innerHTML = `
                <div class="text-center py-8">
                    <i data-lucide="shield-check" class="w-10 h-10 text-emerald-400 mx-auto mb-2 opacity-80"></i>
                    <p class="text-slate-400 text-sm font-medium">Screening Room is Clear</p>
                    <p class="text-slate-500 text-xs">No unsolicited emails pending review.</p>
                </div>
            `;
        } else {
            overviewContainer.innerHTML = items.slice(0, 5).map(it => `
                <div class="p-3 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between">
                    <div class="min-w-0 flex-1 pr-3">
                        <div class="flex items-center space-x-2">
                            <span class="font-semibold text-slate-200 text-xs truncate">${it.sender_name || it.sender_email}</span>
                            <span class="text-[10px] text-slate-500 truncate">&lt;${it.sender_email}&gt;</span>
                        </div>
                        <p class="text-xs text-slate-400 truncate mt-0.5">${it.subject}</p>
                    </div>
                    <div class="flex items-center space-x-1.5 flex-shrink-0">
                        <button onclick="approveQuarantine(${it.id})" class="px-2.5 py-1 bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600 hover:text-white rounded-lg text-xs font-medium transition">Allow</button>
                        <button onclick="blockQuarantine(${it.id})" class="px-2.5 py-1 bg-rose-600/20 text-rose-400 hover:bg-rose-600 hover:text-white rounded-lg text-xs font-medium transition">Block</button>
                    </div>
                </div>
            `).join('');
        }

        const tableBody = document.getElementById('gatekeeperTableBody');
        document.getElementById('gatekeeperTableCount').innerText = `${items.length} items`;
        if (items.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="4" class="py-8 text-center text-slate-500 text-xs">
                        No quarantined emails at this time. Inbound mail meets allowlist or subscription rules.
                    </td>
                </tr>
            `;
        } else {
            tableBody.innerHTML = items.map(it => `
                <tr class="hover:bg-slate-800/30 transition">
                    <td class="py-3 px-4">
                        <div class="font-medium text-slate-200 text-xs">${it.sender_name || it.sender_email}</div>
                        <div class="text-[11px] text-slate-500">${it.sender_email}</div>
                    </td>
                    <td class="py-3 px-4 text-xs text-slate-300 max-w-xs truncate">${it.subject}</td>
                    <td class="py-3 px-4 text-xs text-slate-500 whitespace-nowrap">${it.date || ''}</td>
                    <td class="py-3 px-4 text-right whitespace-nowrap space-x-1">
                        <button onclick="approveQuarantine(${it.id})" title="Approve and move to INBOX" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium transition">
                            Allow to Inbox
                        </button>
                        <button onclick="sendChallenge(${it.id})" title="Send Verification Challenge" class="px-2.5 py-1.5 bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600 hover:text-white rounded-lg text-xs font-medium transition">
                            Challenge
                        </button>
                        <button onclick="blockQuarantine(${it.id})" title="Block & move to Trash" class="px-2.5 py-1.5 bg-rose-600/20 text-rose-400 hover:bg-rose-600 hover:text-white rounded-lg text-xs font-medium transition">
                            Block
                        </button>
                    </td>
                </tr>
            `).join('');
        }
        lucide.createIcons();
    } catch (e) {
        console.error('Quarantine error:', e);
    }
}

async function approveQuarantine(id) {
    try {
        const res = await fetch(`/api/gatekeeper/quarantine/${id}/approve`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, 'success');
        loadQuarantineQueue();
        loadDashboardStats();
    } catch (e) {
        showToast('Error approving message', 'error');
    }
}

async function blockQuarantine(id) {
    try {
        const res = await fetch(`/api/gatekeeper/quarantine/${id}/block`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, 'success');
        loadQuarantineQueue();
        loadDashboardStats();
    } catch (e) {
        showToast('Error blocking message', 'error');
    }
}

async function sendChallenge(id) {
    try {
        const res = await fetch(`/api/gatekeeper/quarantine/${id}/challenge`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, 'info');
    } catch (e) {
        showToast('Error sending challenge', 'error');
    }
}

// 6. Daily Digest Feed
async function loadRollupItems() {
    try {
        const res = await fetch('/api/rollup/items');
        const data = await res.json();
        const items = data.items || [];
        const container = document.getElementById('rollupItemsGrid');

        if (items.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <i data-lucide="layers" class="w-12 h-12 text-purple-400 mx-auto mb-3 opacity-60"></i>
                    <p class="text-slate-300 font-medium text-sm">Your Daily Digest is Calm</p>
                    <p class="text-slate-500 text-xs mt-1">Mark newsletters in Subscriptions Manager with the Digest icon to bundle them here.</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }

        container.innerHTML = items.map(it => `
            <div class="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2 hover:border-purple-500/50 transition">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-semibold text-purple-300 truncate max-w-[180px]">${it.sender_name || it.sender_email}</span>
                    <span class="text-[10px] text-slate-500">${it.date ? it.date.slice(0, 16) : ''}</span>
                </div>
                <h4 class="text-xs font-medium text-slate-200 line-clamp-2">${it.subject}</h4>
                <p class="text-[11px] text-slate-400 line-clamp-3">${it.snippet || it.subject}</p>
                <div class="pt-2 flex items-center justify-between border-t border-slate-800/80">
                    <span class="text-[10px] text-slate-500">&lt;${it.sender_email}&gt;</span>
                    <button onclick="cleanerAction('${it.sender_email}', 'keep')" class="text-[10px] text-indigo-400 hover:text-indigo-300">Move to Inbox</button>
                </div>
            </div>
        `).join('');
        lucide.createIcons();
    } catch (e) {
        console.error('Digest feed error:', e);
    }
}

async function sendRollupDigest() {
    try {
        showToast('Compiling and sending your Daily Digest email...', 'info');
        const res = await fetch('/api/rollup/send-digest', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            loadRollupItems();
        } else {
            showToast(data.message, 'info');
        }
    } catch (e) {
        showToast('Error sending digest', 'error');
    }
}

async function markAllRollupRead() {
    try {
        await fetch('/api/rollup/mark-all-read', { method: 'POST' });
        showToast('Marked all digest items as read', 'success');
        loadRollupItems();
    } catch (e) {
        showToast('Error marking read', 'error');
    }
}

// 7. Rules Logic
async function loadRules() {
    try {
        const resAllow = await fetch('/api/gatekeeper/allowlist');
        const dataAllow = await resAllow.json();
        const allowContainer = document.getElementById('allowlistContainer');
        allowContainer.innerHTML = (dataAllow.allowlist || []).map(r => `
            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs">
                <div>
                    <span class="font-medium text-emerald-400">${r.pattern}</span>
                    <span class="text-[10px] text-slate-500 ml-2">(${r.type} &bull; ${r.reason || 'VIP'})</span>
                </div>
                <button onclick="deleteAllowlistRule(${r.id})" class="text-slate-500 hover:text-rose-400">&times;</button>
            </div>
        `).join('');

        const resBlock = await fetch('/api/gatekeeper/blocklist');
        const dataBlock = await resBlock.json();
        const blockContainer = document.getElementById('blocklistContainer');
        blockContainer.innerHTML = (dataBlock.blocklist || []).map(r => `
            <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs">
                <div>
                    <span class="font-medium text-rose-400">${r.pattern}</span>
                    <span class="text-[10px] text-slate-500 ml-2">(${r.reason || 'Blocked'})</span>
                </div>
                <button onclick="deleteBlocklistRule(${r.id})" class="text-slate-500 hover:text-rose-400">&times;</button>
            </div>
        `).join('');
    } catch (e) {
        console.error('Rules error:', e);
    }
}

async function addAllowlistRule(e) {
    e.preventDefault();
    const pattern = document.getElementById('allowPatternInput').value;
    const type = document.getElementById('allowTypeSelect').value;
    try {
        await fetch('/api/gatekeeper/allowlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pattern: pattern, type: type, reason: 'Manual VIP allowlist' })
        });
        document.getElementById('allowPatternInput').value = '';
        showToast(`Added ${pattern} to VIP Allowlist`, 'success');
        loadRules();
    } catch (e) {
        showToast('Error adding rule', 'error');
    }
}

async function deleteAllowlistRule(id) {
    try {
        await fetch(`/api/gatekeeper/allowlist/${id}`, { method: 'DELETE' });
        loadRules();
    } catch (e) {
        showToast('Error deleting rule', 'error');
    }
}

async function addBlocklistRule(e) {
    e.preventDefault();
    const pattern = document.getElementById('blockPatternInput').value;
    try {
        await fetch('/api/gatekeeper/blocklist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pattern: pattern, type: 'email', reason: 'Manual blocklist' })
        });
        document.getElementById('blockPatternInput').value = '';
        showToast(`Added ${pattern} to Blocklist`, 'success');
        loadRules();
    } catch (e) {
        showToast('Error adding block rule', 'error');
    }
}

async function deleteBlocklistRule(id) {
    try {
        await fetch(`/api/gatekeeper/blocklist/${id}`, { method: 'DELETE' });
        loadRules();
    } catch (e) {
        showToast('Error deleting block rule', 'error');
    }
}

// 8. Settings Logic
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const conf = await res.json();
        document.getElementById('settingsGmailUser').value = conf.gmail_user || '';
        document.getElementById('settingsGatekeeperEnabled').checked = conf.gatekeeper_enabled !== false;
        document.getElementById('settingsAutoChallenge').checked = conf.gatekeeper_auto_challenge === true;
        document.getElementById('settingsChallengeTemplate').value = conf.challenge_template || '';
    } catch (e) {
        console.error('Settings error:', e);
    }
}

async function saveSettings() {
    const user = document.getElementById('settingsGmailUser').value;
    const pass = document.getElementById('settingsGmailPassword').value;
    const gateEnabled = document.getElementById('settingsGatekeeperEnabled').checked;
    const autoChallenge = document.getElementById('settingsAutoChallenge').checked;
    const template = document.getElementById('settingsChallengeTemplate').value;

    const payload = {
        gmail_user: user,
        gatekeeper_enabled: gateEnabled,
        gatekeeper_auto_challenge: autoChallenge,
        challenge_template: template
    };
    if (pass) payload.gmail_app_password = pass;

    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        showToast('Settings saved successfully', 'success');
    } catch (e) {
        showToast('Error saving settings', 'error');
    }
}

async function testConnection() {
    const label = document.getElementById('testConnectionResult');
    label.innerText = 'Testing connection...';
    label.className = 'text-xs text-amber-400';
    try {
        const res = await fetch('/api/settings/test-connection', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            label.innerText = '✓ Connection successful!';
            label.className = 'text-xs text-emerald-400';
            showToast('Gmail IMAP connection verified!', 'success');
        } else {
            label.innerText = `✗ ${data.message}`;
            label.className = 'text-xs text-rose-400';
            showToast(data.message, 'error');
        }
    } catch (e) {
        label.innerText = '✗ Test failed';
        label.className = 'text-xs text-rose-400';
    }
}

// 9. Scan Polling
async function triggerScan(limit = 250) {
    if (isScanning) return;
    try {
        const res = await fetch('/api/scan/trigger', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ limit: limit })
        });
        const data = await res.json();
        if (data.status === 'started') {
            showToast(`Started triage scan of latest ${limit} emails...`, 'info');
            setScanUI(true);
            scanPollInterval = setInterval(checkScanStatus, 2000);
        } else {
            showToast(data.message, 'info');
        }
    } catch (e) {
        showToast('Error starting scan', 'error');
    }
}

async function checkScanStatus() {
    try {
        const res = await fetch('/api/scan/status');
        const data = await res.json();
        if (data.is_scanning) {
            setScanUI(true);
        } else {
            if (isScanning) {
                setScanUI(false);
                if (scanPollInterval) clearInterval(scanPollInterval);
                showToast(data.last_scan_result.message || 'Scan completed!', 'success');
                loadDashboardStats();
                loadQuarantineQueue();
                loadSubscriptions();
                loadAIRecommendations();
                loadActivityLogs();
            }
        }
    } catch (e) {
        console.error('Scan status error:', e);
    }
}

function setScanUI(scanning) {
    isScanning = scanning;
    const scanIcon = document.getElementById('scanIcon');
    const scanBtn = document.getElementById('scanBtn');
    const statusText = document.getElementById('connectionStatusText');

    if (scanning) {
        if (scanIcon) scanIcon.classList.add('animate-spin');
        if (scanBtn) scanBtn.disabled = true;
        if (statusText) statusText.innerText = 'Triaging & Purifying Inbox...';
    } else {
        if (scanIcon) scanIcon.classList.remove('animate-spin');
        if (scanBtn) scanBtn.disabled = false;
        if (statusText) statusText.innerText = 'Connected to Gmail';
    }
}
