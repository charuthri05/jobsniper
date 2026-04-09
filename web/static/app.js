// Job Pipeline Dashboard — Client-side logic

let currentTab = 'queued';
let jobs = [];
let selectedIds = new Set();
let sortField = 'score';
let sortAsc = false;
let currentDetailJob = null;
let resumeMode = 'fast'; // 'fast' or 'thorough'

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
    // Redirect to setup if no profile exists yet (first-time use)
    try {
        const resp = await fetch('/api/profile/full');
        const data = await resp.json();
        if (!data.exists) {
            window.location.href = '/setup';
            return;
        }
    } catch(e) { /* continue to dashboard */ }

    loadJobs('queued');
    loadStats();
    checkRunningTasks();
});

// ---------------------------------------------------------------------------
// Background Task Recovery
// ---------------------------------------------------------------------------

async function checkRunningTasks() {
    try {
        const resp = await fetch('/api/tasks/status');
        const tasks = await resp.json();

        if (tasks.scrape === 'running') {
            attachScrapeSSE();
        }
        if (tasks.generate === 'running') {
            attachGenerateSSE();
        }
        if (tasks.resume === 'running') {
            attachResumeSSE();
        }
        if (tasks.autofill === 'running') {
            attachAutofillSSE();
        }
    } catch(e) { /* silent */ }
}

function attachScrapeSSE() {
    const btn = document.getElementById('btn-scrape');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scraping...';

    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    progressContainer.style.display = 'block';
    progressBar.classList.add('progress-bar-striped', 'progress-bar-animated');
    document.getElementById('progress-label').textContent = 'Scraping jobs...';

    const evtSource = new EventSource('/api/scrape/progress');
    evtSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        progressBar.style.width = pct + '%';
        document.getElementById('progress-count').textContent = `Step ${data.current}/${data.total}`;
        document.getElementById('progress-detail').textContent = data.message;

        if (data.status === 'done') {
            evtSource.close();
            document.getElementById('progress-label').textContent = 'Scrape complete';
            progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');
            progressBar.style.width = '100%';

            const stats = data.stats;
            const msg = stats
                ? `Scrape complete: ${stats.new} new jobs, ${stats.duplicates} duplicates skipped`
                : data.message;

            setTimeout(() => {
                progressContainer.style.display = 'none';
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-cloud-download me-1"></i>Scrape Jobs';
                showToast(msg, 'success');
                loadJobs(currentTab);
                loadStats();
            }, 1500);
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        progressContainer.style.display = 'none';
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-cloud-download me-1"></i>Scrape Jobs';
        loadJobs(currentTab);
        loadStats();
    };
}

function attachGenerateSSE() {
    document.getElementById('progress-container').style.display = 'block';
    document.getElementById('btn-generate').disabled = true;
    document.getElementById('progress-label').textContent = 'Generating cover letters...';

    const evtSource = new EventSource('/api/generate/progress');
    evtSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        document.getElementById('progress-bar').style.width = pct + '%';
        document.getElementById('progress-count').textContent = `${data.current}/${data.total}`;
        document.getElementById('progress-detail').textContent = data.message;

        if (data.status === 'done') {
            evtSource.close();
            setTimeout(() => {
                document.getElementById('progress-container').style.display = 'none';
                document.getElementById('btn-generate').disabled = false;
                loadJobs(currentTab);
                loadStats();
                showToast(data.message, 'success');
            }, 1500);
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('btn-generate').disabled = false;
        loadJobs(currentTab);
        loadStats();
    };
}

function attachResumeSSE() {
    document.getElementById('progress-container').style.display = 'block';
    document.getElementById('btn-generate-resumes').disabled = true;
    document.getElementById('progress-label').textContent = 'Generating tailored resumes...';

    const evtSource = new EventSource('/api/generate-resumes/progress');
    evtSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        document.getElementById('progress-bar').style.width = pct + '%';
        document.getElementById('progress-count').textContent = `${data.current}/${data.total}`;
        document.getElementById('progress-detail').textContent = data.message;

        if (data.status === 'done') {
            evtSource.close();
            setTimeout(() => {
                document.getElementById('progress-container').style.display = 'none';
                document.getElementById('btn-generate-resumes').disabled = false;
                loadJobs(currentTab);
                loadStats();
                showToast(data.message, 'success');
            }, 1500);
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('btn-generate-resumes').disabled = false;
        loadJobs(currentTab);
        loadStats();
    };
}

function attachAutofillSSE() {
    document.getElementById('progress-container').style.display = 'block';
    document.getElementById('btn-autofill').disabled = true;
    document.getElementById('progress-label').textContent = 'Auto-filling applications...';

    const evtSource = new EventSource('/api/autofill/progress');
    evtSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        document.getElementById('progress-bar').style.width = pct + '%';
        document.getElementById('progress-count').textContent = `${data.current}/${data.total}`;
        document.getElementById('progress-detail').textContent = data.message;

        if (data.status === 'done') {
            evtSource.close();
            setTimeout(() => {
                document.getElementById('progress-container').style.display = 'none';
                document.getElementById('btn-autofill').disabled = false;
                showAutofillResults(data.results || []);
                loadJobs(currentTab);
                loadStats();
            }, 1000);
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('btn-autofill').disabled = false;
        loadJobs(currentTab);
        loadStats();
    };
}

// ---------------------------------------------------------------------------
// Data Loading
// ---------------------------------------------------------------------------

async function loadJobs(tab) {
    currentTab = tab;
    selectedIds.clear();
    updateSelectionUI();

    try {
        const resp = await fetch(`/api/jobs?tab=${tab}`);
        jobs = await resp.json();
        sortJobs();
        renderTable();
    } catch (err) {
        showToast('Failed to load jobs', 'error');
    }
}

async function loadStats() {
    try {
        const resp = await fetch('/api/stats');
        const stats = await resp.json();
        document.getElementById('stat-queued').textContent = stats.queued;
        document.getElementById('stat-ready').textContent = stats.ready;
        document.getElementById('stat-submitted').textContent = stats.submitted;
        document.getElementById('badge-queued').textContent = stats.queued;
        document.getElementById('badge-ready').textContent = stats.ready;
        document.getElementById('badge-submitted').textContent = stats.submitted;

        // New tab badges
        const badgeNew = document.getElementById('badge-new');
        if (badgeNew) badgeNew.textContent = stats.new || 0;
        const badgeScored = document.getElementById('badge-scored');
        if (badgeScored) badgeScored.textContent = stats.scored || 0;
        const badgeContract = document.getElementById('badge-contract');
        if (badgeContract) badgeContract.textContent = stats.contract || 0;
    } catch (err) { /* silent */ }
}

function refreshAll() {
    loadJobs(currentTab);
    loadStats();
    showToast('Refreshed', 'success');
}

// ---------------------------------------------------------------------------
// Tab Switching
// ---------------------------------------------------------------------------

function switchTab(tab) {
    document.querySelectorAll('[data-tab]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // Show/hide action buttons based on tab
    const isActionable = (tab === 'queued' || tab === 'ready' || tab === 'new' || tab === 'scored' || tab === 'contract');
    document.getElementById('action-buttons').style.display = isActionable ? 'flex' : 'none';

    // Generate button only on Queued tab, Submit available on actionable tabs
    document.getElementById('btn-generate').style.display = (tab === 'queued') ? 'inline-block' : 'none';

    loadJobs(tab);
}

// ---------------------------------------------------------------------------
// Table Rendering
// ---------------------------------------------------------------------------

function renderTable() {
    const tbody = document.getElementById('job-tbody');
    const empty = document.getElementById('empty-state');

    if (jobs.length === 0) {
        tbody.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';

    tbody.innerHTML = jobs.map(job => {
        const scoreClass = job.score >= 80 ? 'score-high' : job.score >= 72 ? 'score-mid' : 'score-low';
        const clIcon = job.has_cover_letter
            ? `<a href="/api/job/${job.id}/cover-letter/download?format=pdf" download onclick="event.stopPropagation()" title="Download cover letter PDF" class="text-success"><i class="bi bi-file-earmark-arrow-down-fill"></i></a>`
            : '<i class="bi bi-dash-circle cl-no"></i>';
        const cvIcon = job.has_resume
            ? `<a href="/api/job/${job.id}/resume/download" download onclick="event.stopPropagation()" title="Download tailored resume" class="text-success"><i class="bi bi-file-earmark-arrow-down-fill"></i></a>`
            : '<i class="bi bi-dash-circle cl-no"></i>';
        const checked = selectedIds.has(job.id) ? 'checked' : '';
        const selectedClass = selectedIds.has(job.id) ? 'selected' : '';
        const location = job.location || '--';
        const truncTitle = job.title.length > 50 ? job.title.substring(0, 47) + '...' : job.title;

        return `
            <tr class="${selectedClass}" data-id="${job.id}">
                <td onclick="event.stopPropagation()">
                    <input type="checkbox" class="form-check-input row-check"
                           ${checked} onchange="toggleSelect('${job.id}', this)">
                </td>
                <td><span class="badge ${scoreClass}">${job.score ?? '--'}</span></td>
                <td class="fw-medium" onclick="openDetail('${job.id}')" title="${escapeHtml(job.title)}">
                    ${escapeHtml(truncTitle)}
                </td>
                <td onclick="openDetail('${job.id}')">${escapeHtml(job.company)}</td>
                <td onclick="openDetail('${job.id}')" class="text-muted small">${escapeHtml(location)}</td>
                <td>${clIcon}</td>
                <td>${cvIcon}</td>
                <td class="text-nowrap" onclick="event.stopPropagation()">
                    <a href="javascript:void(0)" onclick="quickMarkApplied('${job.id}')" class="row-action text-success" title="Mark as applied">
                        <i class="bi bi-check-circle"></i>
                    </a>
                    <a href="javascript:void(0)" onclick="quickSkip('${job.id}')" class="row-action text-danger ms-1" title="Not interested">
                        <i class="bi bi-x-circle"></i>
                    </a>
                    <a href="${job.url}" target="_blank" onclick="trackOpenPosting('${job.id}', '${escapeHtml(job.title)}', '${escapeHtml(job.company)}')" class="row-action text-muted ms-1" title="Open posting">
                        <i class="bi bi-box-arrow-up-right"></i>
                    </a>
                </td>
            </tr>
        `;
    }).join('');
}

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

function sortTable(field) {
    if (sortField === field) {
        sortAsc = !sortAsc;
    } else {
        sortField = field;
        sortAsc = field !== 'score'; // default desc for score, asc for text
    }
    sortJobs();
    renderTable();
}

function sortJobs() {
    jobs.sort((a, b) => {
        let va = a[sortField] ?? '';
        let vb = b[sortField] ?? '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

function toggleSelect(id, checkbox) {
    if (checkbox.checked) {
        selectedIds.add(id);
    } else {
        selectedIds.delete(id);
    }
    // Highlight row
    const row = checkbox.closest('tr');
    row.classList.toggle('selected', checkbox.checked);
    updateSelectionUI();
}

function toggleSelectAll(masterCheckbox) {
    if (masterCheckbox.checked) {
        jobs.forEach(j => selectedIds.add(j.id));
    } else {
        selectedIds.clear();
    }
    renderTable();
    updateSelectionUI();
}

function updateSelectionUI() {
    const count = selectedIds.size;
    const countEl = document.getElementById('selection-count');
    const selCountEl = document.getElementById('sel-count');

    if (count > 0) {
        countEl.style.display = 'inline';
        selCountEl.textContent = count;
    } else {
        countEl.style.display = 'none';
    }

    // Enable/disable action buttons
    document.getElementById('btn-generate').disabled = count === 0;
    document.getElementById('btn-generate-resumes').disabled = count === 0;
    document.getElementById('btn-resume-mode-toggle').disabled = count === 0;
    document.getElementById('btn-autofill').disabled = count === 0;
    document.getElementById('btn-skip').disabled = count === 0;

    // Update master checkbox
    const master = document.getElementById('select-all');
    if (jobs.length > 0 && count === jobs.length) {
        master.checked = true;
        master.indeterminate = false;
    } else if (count > 0) {
        master.checked = false;
        master.indeterminate = true;
    } else {
        master.checked = false;
        master.indeterminate = false;
    }
}

// ---------------------------------------------------------------------------
// Detail Modal
// ---------------------------------------------------------------------------

async function openDetail(jobId) {
    try {
        const resp = await fetch(`/api/job/${jobId}`);
        const job = await resp.json();
        currentDetailJob = job;

        document.getElementById('detail-title').textContent = job.title;
        document.getElementById('detail-company').textContent = `${job.company} · ${job.location || 'No location'}`;
        document.getElementById('detail-score').textContent = `Score: ${job.score ?? '--'}/100`;
        document.getElementById('detail-location').textContent = job.location || '--';
        document.getElementById('detail-source').textContent = job.source || '--';
        document.getElementById('detail-reason').textContent = job.score_reason || '';
        document.getElementById('detail-url').href = job.url;

        // Strengths
        const strengthsList = document.getElementById('detail-strengths');
        strengthsList.innerHTML = (job.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('') || '<li class="text-muted">--</li>';

        // Missing
        const missingList = document.getElementById('detail-missing');
        missingList.innerHTML = (job.missing || []).map(m => `<li>${escapeHtml(m)}</li>`).join('') || '<li class="text-muted">--</li>';

        // Cover Letter
        const clDisplay = document.getElementById('cl-display');
        const clEditor = document.getElementById('cl-editor');
        const editActions = document.getElementById('cl-edit-actions');
        const btnEditCL = document.getElementById('btn-edit-cl');

        clEditor.style.display = 'none';
        editActions.style.display = 'none';
        clDisplay.style.display = 'block';

        const btnDownloadCL = document.getElementById('btn-download-cl');
        if (job.cover_letter) {
            clDisplay.textContent = job.cover_letter;
            btnEditCL.style.display = 'inline-block';
            btnDownloadCL.style.display = 'inline-block';
            // Set actual download URLs
            document.getElementById('dl-pdf').href = `/api/job/${job.id}/cover-letter/download?format=pdf`;
            document.getElementById('dl-docx').href = `/api/job/${job.id}/cover-letter/download?format=docx`;
            document.getElementById('dl-txt').href = `/api/job/${job.id}/cover-letter/download?format=txt`;
        } else {
            clDisplay.innerHTML = '<span class="text-muted fst-italic">Not yet generated. Select this job and click "Generate Cover Letters".</span>';
            btnEditCL.style.display = 'none';
            btnDownloadCL.style.display = 'none';
        }

        // Tailored Resume download button
        const btnDownloadResume = document.getElementById('btn-download-resume');
        if (job.has_resume) {
            btnDownloadResume.style.display = 'inline-block';
        } else {
            btnDownloadResume.style.display = 'none';
        }

        // Resume Bullets
        const bulletsSection = document.getElementById('bullets-section');
        const bulletsList = document.getElementById('detail-bullets');
        if (job.resume_bullets && job.resume_bullets.length > 0) {
            bulletsList.innerHTML = job.resume_bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('');
            bulletsSection.style.display = 'block';
        } else {
            bulletsSection.style.display = 'none';
        }

        // Job Description
        const desc = job.description || 'No description available';
        document.getElementById('detail-description').textContent = desc;

        new bootstrap.Modal(document.getElementById('detailModal')).show();
    } catch (err) {
        showToast('Failed to load job details', 'error');
    }
}

// ---------------------------------------------------------------------------
// Cover Letter Edit
// ---------------------------------------------------------------------------

function toggleEditCL() {
    const clDisplay = document.getElementById('cl-display');
    const clEditor = document.getElementById('cl-editor');
    const editActions = document.getElementById('cl-edit-actions');

    clDisplay.style.display = 'none';
    clEditor.style.display = 'block';
    editActions.style.display = 'block';
    clEditor.value = currentDetailJob.cover_letter || '';
    clEditor.focus();
}

function cancelEditCL() {
    document.getElementById('cl-display').style.display = 'block';
    document.getElementById('cl-editor').style.display = 'none';
    document.getElementById('cl-edit-actions').style.display = 'none';
}

function downloadResume() {
    if (currentDetailJob && currentDetailJob.id) {
        window.open(`/api/job/${currentDetailJob.id}/resume/download`, '_blank');
    }
}

async function saveCoverLetter() {
    const newCL = document.getElementById('cl-editor').value;
    try {
        await fetch(`/api/job/${currentDetailJob.id}/cover-letter`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({cover_letter: newCL})
        });
        currentDetailJob.cover_letter = newCL;
        document.getElementById('cl-display').textContent = newCL;
        cancelEditCL();
        showToast('Cover letter saved', 'success');
        loadJobs(currentTab);
        loadStats();
    } catch (err) {
        showToast('Failed to save', 'error');
    }
}

// ---------------------------------------------------------------------------
// Generate Cover Letters
// ---------------------------------------------------------------------------

// IDs that were just generated (for results modal)
let lastGeneratedIds = [];

async function generateSelected() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    showConfirm(`Generate cover letters for ${ids.length} job(s)?`, async () => {
        lastGeneratedIds = [...ids];

        try {
            const resp = await fetch('/api/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({job_ids: ids})
            });

            if (resp.status === 409) {
                showToast('Generation already in progress', 'warning');
                return;
            }

            // Show progress and start SSE listener
            document.getElementById('progress-container').style.display = 'block';
            document.getElementById('btn-generate').disabled = true;

            const evtSource = new EventSource('/api/generate/progress');
            evtSource.onmessage = (e) => {
                const data = JSON.parse(e.data);
                const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;

                document.getElementById('progress-bar').style.width = pct + '%';
                document.getElementById('progress-count').textContent = `${data.current}/${data.total}`;
                document.getElementById('progress-detail').textContent = data.message;
                document.getElementById('progress-label').textContent =
                    data.status === 'done' ? 'Complete' : 'Generating cover letters...';

                if (data.status === 'done') {
                    evtSource.close();
                    setTimeout(() => {
                        document.getElementById('progress-container').style.display = 'none';
                        document.getElementById('btn-generate').disabled = false;
                        loadJobs(currentTab);
                        loadStats();
                        showGenerationResults(lastGeneratedIds);
                    }, 1500);
                }
            };

            evtSource.onerror = () => {
                evtSource.close();
                document.getElementById('progress-container').style.display = 'none';
                document.getElementById('btn-generate').disabled = false;
                loadJobs(currentTab);
                loadStats();
            };
        } catch (err) {
            showToast('Failed to start generation', 'error');
        }
    });
}

// ---------------------------------------------------------------------------
// Resume Generation
// ---------------------------------------------------------------------------

let lastResumeGeneratedIds = [];

function setResumeMode(mode) {
    resumeMode = mode;
    const btn = document.getElementById('btn-generate-resumes');
    if (mode === 'fast') {
        btn.innerHTML = '<i class="bi bi-lightning-fill me-1"></i>Fast Resume';
        showToast('Fast mode: Plan + Execute (skip review)', 'info');
    } else {
        btn.innerHTML = '<i class="bi bi-shield-check me-1"></i>Thorough Resume';
        showToast('Thorough mode: Plan + Review + Execute', 'info');
    }
}

let _resumePollingIds = new Set(); // track all job IDs being generated

async function generateResumes() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    const modeLabel = resumeMode === 'fast' ? 'Fast (Plan + Execute)' : 'Thorough (Plan + Review + Execute)';
    showConfirm(`Generate ${modeLabel} resumes for ${ids.length} job(s)?`, async () => {
        try {
            const resp = await fetch('/api/generate-resumes', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({job_ids: ids, mode: resumeMode})
            });

            if (!resp.ok) {
                const data = await resp.json();
                showToast(data.error || 'Failed to start', 'error');
                return;
            }

            showToast(`${ids.length} resume(s) generating in background. Download icons will appear when ready.`, 'success');

            // Add to tracking set and start polling if not already
            ids.forEach(id => _resumePollingIds.add(id));
            startResumePolling();

        } catch (err) {
            showToast('Failed to start resume generation', 'error');
        }
    });
}

let _resumePollingTimer = null;

function startResumePolling() {
    if (_resumePollingTimer) return; // already polling

    _resumePollingTimer = setInterval(async () => {
        if (_resumePollingIds.size === 0) {
            clearInterval(_resumePollingTimer);
            _resumePollingTimer = null;
            return;
        }

        try {
            const resp = await fetch('/api/resume-jobs/status');
            const statuses = await resp.json();

            let anyDone = false;
            for (const [jobId, info] of Object.entries(statuses)) {
                if (!_resumePollingIds.has(jobId)) continue;

                if (info.status === 'done') {
                    _resumePollingIds.delete(jobId);
                    anyDone = true;
                } else if (info.status === 'error') {
                    _resumePollingIds.delete(jobId);
                    showToast(`Resume failed: ${info.message}`, 'error');
                }
            }

            if (anyDone) {
                loadJobs(currentTab); // refresh table to show download icons
            }

            if (_resumePollingIds.size === 0) {
                clearInterval(_resumePollingTimer);
                _resumePollingTimer = null;
                showToast('All resumes generated!', 'success');
                loadJobs(currentTab);
                loadStats();
            }
        } catch(e) {
            // silent
        }
    }, 3000); // poll every 3 seconds
}

// ---------------------------------------------------------------------------
// Resume Results Modal
// ---------------------------------------------------------------------------

async function showResumeResults(jobIds) {
    const body = document.getElementById('resume-results-body');
    body.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm"></div> Loading results...</div>';

    const modal = new bootstrap.Modal(document.getElementById('resumeResultsModal'));
    modal.show();

    // Fetch each job's data and check if resume PDF exists
    const results = [];
    for (const id of jobIds) {
        try {
            const resp = await fetch(`/api/job/${id}`);
            if (resp.ok) {
                const job = await resp.json();
                // Check if resume file exists by trying a HEAD request
                const resumeResp = await fetch(`/api/job/${id}/resume/download`, {method: 'HEAD'});
                job._hasResume = resumeResp.ok;
                results.push(job);
            }
        } catch (e) { /* skip */ }
    }

    const withResume = results.filter(j => j._hasResume);
    const withoutResume = results.filter(j => !j._hasResume);

    let html = `<p class="text-muted small mb-3">${withResume.length} of ${results.length} resume(s) generated successfully.</p>`;

    if (withResume.length === 0) {
        html += '<div class="alert alert-warning">No resumes were generated. Check the logs for errors.</div>';
        body.innerHTML = html;
        return;
    }

    withResume.forEach(job => {
        html += `
            <div class="border rounded mb-3 resume-result-card" data-job-id="${job.id}">
                <div class="d-flex justify-content-between align-items-center p-3 bg-light" style="border-radius: 8px 8px 0 0;">
                    <div>
                        <strong>${escapeHtml(job.title)}</strong>
                        <span class="text-muted"> at ${escapeHtml(job.company)}</span>
                        <span class="badge bg-success-subtle text-success ms-2">Score: ${job.score ?? '--'}</span>
                    </div>
                    <div class="d-flex gap-2">
                        <a href="/api/job/${job.id}/resume/download" target="_blank" class="btn btn-sm btn-outline-primary">
                            <i class="bi bi-eye me-1"></i>View PDF
                        </a>
                        <a href="/api/job/${job.id}/resume/download" download class="btn btn-sm btn-outline-secondary">
                            <i class="bi bi-download me-1"></i>Download
                        </a>
                    </div>
                </div>
            </div>`;
    });

    if (withoutResume.length > 0) {
        html += `<div class="mt-3"><p class="text-muted small mb-2">Failed to generate (${withoutResume.length}):</p>`;
        withoutResume.forEach(job => {
            html += `<div class="border rounded p-2 mb-1 d-flex align-items-center">
                <i class="bi bi-exclamation-circle text-danger me-2"></i>
                <span class="small">${escapeHtml(job.title)} at ${escapeHtml(job.company)}</span>
            </div>`;
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

async function downloadAllResumes() {
    const cards = document.querySelectorAll('.resume-result-card');
    const jobIds = [];
    cards.forEach(card => {
        if (card.dataset.jobId) jobIds.push(card.dataset.jobId);
    });

    if (jobIds.length === 0) return;

    try {
        const resp = await fetch('/api/resumes/download-all', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: jobIds})
        });

        if (!resp.ok) {
            showToast('Failed to generate ZIP', 'error');
            return;
        }

        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const disposition = resp.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?(.+?)"?$/);
        a.download = match ? match[1] : `Tailored_Resumes_${jobIds.length}_jobs.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        showToast('Download failed: ' + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Cover Letter Generation Results Modal
// ---------------------------------------------------------------------------

async function showGenerationResults(jobIds) {
    const body = document.getElementById('gen-results-body');
    body.innerHTML = '<div class="text-center py-3"><div class="spinner-border spinner-border-sm"></div> Loading results...</div>';

    const modal = new bootstrap.Modal(document.getElementById('genResultsModal'));
    modal.show();

    // Fetch each job's updated data
    const results = [];
    for (const id of jobIds) {
        try {
            const resp = await fetch(`/api/job/${id}`);
            if (resp.ok) results.push(await resp.json());
        } catch (e) { /* skip */ }
    }

    const withCL = results.filter(j => j.cover_letter);
    const withoutCL = results.filter(j => !j.cover_letter);

    let html = `<p class="text-muted small mb-3">${withCL.length} of ${results.length} cover letter(s) generated successfully.</p>`;

    if (withCL.length === 0) {
        html += '<div class="alert alert-warning">No cover letters were generated. Check the generation logs for errors.</div>';
        body.innerHTML = html;
        return;
    }

    withCL.forEach((job, idx) => {
        const preview = job.cover_letter.length > 300
            ? job.cover_letter.substring(0, 300) + '...'
            : job.cover_letter;

        html += `
            <div class="border rounded mb-3 gen-result-card" data-job-id="${job.id}">
                <div class="d-flex justify-content-between align-items-center p-3 border-bottom bg-light" style="border-radius: 8px 8px 0 0;">
                    <div>
                        <strong>${escapeHtml(job.title)}</strong>
                        <span class="text-muted"> at ${escapeHtml(job.company)}</span>
                        <span class="badge bg-success-subtle text-success ms-2">Score: ${job.score ?? '--'}</span>
                    </div>
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-outline-primary" onclick="toggleGenCLView(${idx})">
                            <i class="bi bi-eye me-1"></i><span id="gen-toggle-text-${idx}">View Full</span>
                        </button>
                        <div class="dropdown">
                            <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">
                                <i class="bi bi-download me-1"></i>Download
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end">
                                <li><a class="dropdown-item" href="/api/job/${job.id}/cover-letter/download?format=pdf" download><i class="bi bi-file-earmark-pdf me-2 text-danger"></i>PDF</a></li>
                                <li><a class="dropdown-item" href="/api/job/${job.id}/cover-letter/download?format=docx" download><i class="bi bi-file-earmark-word me-2 text-primary"></i>Word</a></li>
                                <li><a class="dropdown-item" href="/api/job/${job.id}/cover-letter/download?format=txt" download><i class="bi bi-file-earmark-text me-2 text-secondary"></i>Text</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
                <div class="p-3">
                    <div id="gen-cl-preview-${idx}" style="white-space: pre-wrap; font-size: 0.9rem;">${escapeHtml(preview)}</div>
                    <div id="gen-cl-full-${idx}" style="white-space: pre-wrap; font-size: 0.9rem; display: none;">${escapeHtml(job.cover_letter)}</div>
                </div>
            </div>`;
    });

    if (withoutCL.length > 0) {
        html += `<div class="mt-3"><p class="text-muted small mb-2">Failed to generate (${withoutCL.length}):</p>`;
        withoutCL.forEach(job => {
            html += `<div class="border rounded p-2 mb-1 d-flex align-items-center">
                <i class="bi bi-exclamation-circle text-danger me-2"></i>
                <span class="small">${escapeHtml(job.title)} at ${escapeHtml(job.company)}</span>
            </div>`;
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

function toggleGenCLView(idx) {
    const preview = document.getElementById(`gen-cl-preview-${idx}`);
    const full = document.getElementById(`gen-cl-full-${idx}`);
    const toggleText = document.getElementById(`gen-toggle-text-${idx}`);

    if (full.style.display === 'none') {
        preview.style.display = 'none';
        full.style.display = 'block';
        toggleText.textContent = 'Preview';
    } else {
        preview.style.display = 'block';
        full.style.display = 'none';
        toggleText.textContent = 'View Full';
    }
}

async function downloadAllCoverLetters(format = 'pdf') {
    const cards = document.querySelectorAll('.gen-result-card');
    const jobIds = [];
    cards.forEach(card => {
        if (card.dataset.jobId) jobIds.push(card.dataset.jobId);
    });

    if (jobIds.length === 0) return;

    try {
        const resp = await fetch('/api/cover-letters/download-all', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: jobIds, format: format})
        });

        if (!resp.ok) {
            showToast('Failed to generate ZIP', 'error');
            return;
        }

        // Download the ZIP blob
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        // Extract filename from Content-Disposition header
        const disposition = resp.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?(.+?)"?$/);
        a.download = match ? match[1] : `Cover_Letters_${jobIds.length}_jobs.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        showToast('Download failed: ' + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Submit Applications
// ---------------------------------------------------------------------------

// IDs staged for submission after preview
let pendingSubmitIds = [];

async function submitSelected() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    // Fetch preview data (profile fields + job details)
    try {
        const resp = await fetch('/api/submit/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: ids})
        });
        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        // Populate profile fields
        const p = data.profile;
        document.getElementById('preview-first-name').textContent = p.first_name;
        document.getElementById('preview-last-name').textContent = p.last_name;
        document.getElementById('preview-email').textContent = p.email;
        document.getElementById('preview-phone').textContent = p.phone;
        document.getElementById('preview-location').textContent = p.location;
        document.getElementById('preview-linkedin').textContent = p.linkedin;
        document.getElementById('preview-github').textContent = p.github;

        // Populate job list
        document.getElementById('preview-job-count').textContent = data.jobs.length;
        const jobsHtml = data.jobs.map(j => {
            const clBadge = j.has_cover_letter
                ? '<span class="badge bg-success-subtle text-success">Cover Letter</span>'
                : '<span class="badge bg-warning-subtle text-warning">No Cover Letter</span>';
            const clPreview = j.has_cover_letter && j.cover_letter_preview
                ? `<div class="text-muted small mt-1" style="white-space:pre-wrap;">${escapeHtml(j.cover_letter_preview)}</div>`
                : '';
            return `
                <div class="border rounded p-3 mb-2">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <strong>${escapeHtml(j.title)}</strong>
                            <span class="text-muted"> at ${escapeHtml(j.company)}</span>
                        </div>
                        <div class="d-flex gap-2 align-items-center">
                            ${clBadge}
                            <a href="${j.url}" target="_blank" class="text-muted" title="Preview posting">
                                <i class="bi bi-box-arrow-up-right"></i>
                            </a>
                        </div>
                    </div>
                    ${clPreview}
                </div>
            `;
        }).join('');
        document.getElementById('preview-jobs-list').innerHTML = jobsHtml;

        // Store IDs and show modal
        pendingSubmitIds = data.jobs.map(j => j.id);
        new bootstrap.Modal(document.getElementById('submitPreviewModal')).show();

    } catch (err) {
        showToast('Failed to load preview: ' + err.message, 'error');
    }
}

async function confirmSubmit() {
    if (pendingSubmitIds.length === 0) return;

    // Close preview modal
    bootstrap.Modal.getInstance(document.getElementById('submitPreviewModal')).hide();

    try {
        document.getElementById('btn-submit').disabled = true;
        document.getElementById('btn-submit').innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Processing...';

        const resp = await fetch('/api/submit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: pendingSubmitIds})
        });
        const data = await resp.json();

        // Open each job URL in a new tab
        const urls = data.urls || [];
        urls.forEach(url => window.open(url, '_blank'));

        const submitted = data.results.filter(r => r.status === 'submitted').length;
        showToast(`${submitted} job(s) opened in new tabs and marked as submitted`, 'success');
        pendingSubmitIds = [];
        loadJobs(currentTab);
        loadStats();
    } catch (err) {
        showToast('Submission failed: ' + err.message, 'error');
    } finally {
        document.getElementById('btn-submit').disabled = false;
        document.getElementById('btn-submit').innerHTML = '<i class="bi bi-send me-1"></i>Submit Selected';
    }
}

// ---------------------------------------------------------------------------
// Skip Jobs
// ---------------------------------------------------------------------------

async function skipSelected() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    showConfirm(`Skip ${ids.length} job(s)? They won't appear again.`, async () => {
        try {
            await fetch('/api/skip', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({job_ids: ids})
            });
            showToast(`Skipped ${ids.length} jobs`, 'success');
            loadJobs(currentTab);
            loadStats();
        } catch (err) {
            showToast('Failed to skip', 'error');
        }
    });
}

// ---------------------------------------------------------------------------
// Quick Row Actions
// ---------------------------------------------------------------------------

async function quickMarkApplied(jobId) {
    try {
        await fetch(`/api/job/${jobId}/mark-applied`, {method: 'POST'});
        // Remove row with animation
        const row = document.querySelector(`tr[data-id="${jobId}"]`);
        if (row) {
            row.style.transition = 'opacity 0.3s, background 0.3s';
            row.style.backgroundColor = '#d1e7dd';
            row.style.opacity = '0';
            setTimeout(() => {
                jobs = jobs.filter(j => j.id !== jobId);
                renderTable();
                loadStats();
            }, 350);
        }
        showToast('Marked as applied', 'success');
    } catch(e) {
        showToast('Failed to mark as applied', 'error');
    }
}

async function quickSkip(jobId) {
    try {
        await fetch(`/api/job/${jobId}/skip`, {method: 'POST'});
        const row = document.querySelector(`tr[data-id="${jobId}"]`);
        if (row) {
            row.style.transition = 'opacity 0.3s, background 0.3s';
            row.style.backgroundColor = '#f8d7da';
            row.style.opacity = '0';
            setTimeout(() => {
                jobs = jobs.filter(j => j.id !== jobId);
                renderTable();
                loadStats();
            }, 350);
        }
        showToast('Job dismissed', 'info');
    } catch(e) {
        showToast('Failed to dismiss', 'error');
    }
}

// ---------------------------------------------------------------------------
// "Did you apply?" popup on return from external tab
// ---------------------------------------------------------------------------

let lastOpenedJob = null;

function trackOpenPosting(jobId, title, company) {
    lastOpenedJob = {id: jobId, title, company};
}

// Detect when user returns to this tab after opening a job posting
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && lastOpenedJob) {
        const job = lastOpenedJob;
        lastOpenedJob = null; // Only show once

        // Small delay so the page settles
        setTimeout(() => {
            showApplyPrompt(job);
        }, 500);
    }
});

function showApplyPrompt(job) {
    // Create a floating prompt at the top of the page
    const existing = document.getElementById('apply-prompt');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.id = 'apply-prompt';
    div.className = 'apply-prompt';
    div.innerHTML = `
        <div class="d-flex align-items-center justify-content-between">
            <div>
                <i class="bi bi-question-circle text-primary me-2"></i>
                <strong>Did you apply to ${escapeHtml(job.title)}</strong>
                <span class="text-muted"> at ${escapeHtml(job.company)}?</span>
            </div>
            <div class="d-flex gap-2">
                <button class="btn btn-success btn-sm" onclick="confirmApplied('${job.id}')">
                    <i class="bi bi-check-lg me-1"></i>Yes, applied
                </button>
                <button class="btn btn-outline-secondary btn-sm" onclick="dismissApplyPrompt()">
                    Not yet
                </button>
                <button class="btn btn-outline-danger btn-sm" onclick="confirmSkipFromPrompt('${job.id}')">
                    Not interested
                </button>
            </div>
        </div>
    `;
    document.body.prepend(div);

    // Auto-dismiss after 15 seconds
    setTimeout(() => {
        dismissApplyPrompt();
    }, 15000);
}

function confirmApplied(jobId) {
    dismissApplyPrompt();
    quickMarkApplied(jobId);
}

function confirmSkipFromPrompt(jobId) {
    dismissApplyPrompt();
    quickSkip(jobId);
}

function dismissApplyPrompt() {
    const el = document.getElementById('apply-prompt');
    if (el) {
        el.style.transition = 'opacity 0.3s, transform 0.3s';
        el.style.opacity = '0';
        el.style.transform = 'translateY(-20px)';
        setTimeout(() => el.remove(), 300);
    }
}

// ---------------------------------------------------------------------------
// Add Job by URL
// ---------------------------------------------------------------------------

function showAddJobModal() {
    document.getElementById('add-job-url').value = '';
    document.getElementById('add-job-status').innerHTML = '';
    document.getElementById('btn-add-job').disabled = false;
    document.getElementById('btn-add-job').innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Job';
    new bootstrap.Modal(document.getElementById('addJobModal')).show();
    setTimeout(() => document.getElementById('add-job-url').focus(), 300);
}

async function addJobByUrl() {
    const url = document.getElementById('add-job-url').value.trim();
    if (!url) {
        document.getElementById('add-job-status').innerHTML = '<span class="text-danger">Please enter a URL</span>';
        return;
    }

    const btn = document.getElementById('btn-add-job');
    const status = document.getElementById('add-job-status');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Fetching...';
    status.innerHTML = '<span class="text-primary"><span class="spinner-border spinner-border-sm me-1"></span>Fetching page and extracting job details...</span>';

    try {
        const resp = await fetch('/api/jobs/add-by-url', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url})
        });
        const data = await resp.json();

        if (!resp.ok) {
            status.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>${data.error}</span>`;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Job';
            return;
        }

        const job = data.job;
        status.innerHTML = `<span class="text-success"><i class="bi bi-check-circle me-1"></i>Added: <strong>${escapeHtml(job.title)}</strong> at ${escapeHtml(job.company)}</span>`;

        // Close modal after brief delay and refresh
        setTimeout(() => {
            bootstrap.Modal.getInstance(document.getElementById('addJobModal')).hide();
            showToast(`Added: ${job.title} at ${job.company}`, 'success');
            loadJobs(currentTab);
            loadStats();
        }, 1500);

    } catch(e) {
        status.innerHTML = `<span class="text-danger">Failed: ${e.message}</span>`;
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Job';
    }
}

// Allow Enter key to submit
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('addJobModal').classList.contains('show')) {
        e.preventDefault();
        addJobByUrl();
    }
});

// ---------------------------------------------------------------------------
// Scrape Jobs
// ---------------------------------------------------------------------------

function startScrape() {
    showConfirm('Run all scrapers? This may take a few minutes.', async () => {
        try {
            const resp = await fetch('/api/scrape', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
            });

            if (resp.status === 409) {
                showToast('Scrape already in progress', 'warning');
                return;
            }

            attachScrapeSSE();
        } catch (err) {
            showToast('Failed to start scrape: ' + err.message, 'error');
        }
    });
}

// ---------------------------------------------------------------------------
// Score Jobs
// ---------------------------------------------------------------------------

function startScore() {
    showConfirm('Score all new jobs with AI? This may take a few minutes.', async () => {
        const btn = document.getElementById('btn-score');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scoring...';

        try {
            const resp = await fetch('/api/score', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
            });

            if (resp.status === 409) {
                showToast('Scoring already in progress', 'warning');
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-stars me-1"></i>Score Jobs';
                return;
            }

            // Show progress bar
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progress-bar');
            progressContainer.style.display = 'block';
            progressBar.classList.add('progress-bar-striped', 'progress-bar-animated');
            document.getElementById('progress-label').textContent = 'Scoring jobs...';
            document.getElementById('progress-count').textContent = '';
            document.getElementById('progress-detail').textContent = '';

            const evtSource = new EventSource('/api/score/progress');
            evtSource.onmessage = (e) => {
                const data = JSON.parse(e.data);
                const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
                progressBar.style.width = pct + '%';
                document.getElementById('progress-count').textContent = `Step ${data.current}/${data.total}`;
                document.getElementById('progress-detail').textContent = data.message;

                if (data.status === 'done') {
                    evtSource.close();
                    document.getElementById('progress-label').textContent = 'Scoring complete';
                    progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');
                    progressBar.style.width = '100%';

                    const stats = data.stats;
                    const msg = stats
                        ? `Scoring complete: ${stats.queued || 0} queued, ${stats.scored || 0} scored, ${stats.filtered_out || 0} filtered out`
                        : data.message;

                    setTimeout(() => {
                        progressContainer.style.display = 'none';
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-stars me-1"></i>Score Jobs';
                        showToast(msg, 'success');
                        loadJobs(currentTab);
                        loadStats();
                    }, 1500);
                }
            };

            evtSource.onerror = () => {
                evtSource.close();
                progressContainer.style.display = 'none';
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-stars me-1"></i>Score Jobs';
                loadJobs(currentTab);
                loadStats();
            };

        } catch (err) {
            showToast('Failed to start scoring: ' + err.message, 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-stars me-1"></i>Score Jobs';
        }
    });
}

// ---------------------------------------------------------------------------
// Confirm Modal
// ---------------------------------------------------------------------------

function showConfirm(message, onConfirm) {
    document.getElementById('confirm-text').textContent = message;
    const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    const okBtn = document.getElementById('confirm-ok');

    // Remove old listener
    const newOkBtn = okBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOkBtn, okBtn);

    newOkBtn.addEventListener('click', () => {
        modal.hide();
        onConfirm();
    });

    modal.show();
}

// ---------------------------------------------------------------------------
// Toast Notifications
// ---------------------------------------------------------------------------

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    const icon = document.getElementById('toast-icon');
    const msg = document.getElementById('toast-message');

    msg.textContent = message;
    toast.className = 'toast';

    if (type === 'success') {
        toast.classList.add('text-bg-success');
        icon.className = 'bi bi-check-circle-fill';
    } else if (type === 'error') {
        toast.classList.add('text-bg-danger');
        icon.className = 'bi bi-exclamation-circle-fill';
    } else if (type === 'warning') {
        toast.classList.add('text-bg-warning');
        icon.className = 'bi bi-exclamation-triangle-fill';
    } else {
        toast.classList.add('text-bg-light');
        icon.className = 'bi bi-info-circle-fill';
    }

    new bootstrap.Toast(toast, {delay: 3000}).show();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}


// ---------------------------------------------------------------------------
// Auto-Fill (Playwright)
// ---------------------------------------------------------------------------

let pendingAutofillIds = [];

async function autofillSelected() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    try {
        const resp = await fetch('/api/submit/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: ids})
        });
        const data = await resp.json();
        if (data.error) { showToast(data.error, 'error'); return; }

        const p = data.profile;
        document.getElementById('af-first-name').textContent = p.first_name;
        document.getElementById('af-last-name').textContent = p.last_name;
        document.getElementById('af-email').textContent = p.email;
        document.getElementById('af-phone').textContent = p.phone;
        document.getElementById('af-location').textContent = p.location;
        document.getElementById('af-linkedin').textContent = p.linkedin;
        document.getElementById('af-github').textContent = p.github;

        const withCL = data.jobs.filter(j => j.has_cover_letter).length;
        document.getElementById('af-cl-status').textContent = `${withCL}/${data.jobs.length} jobs have cover letters`;

        document.getElementById('af-job-count').textContent = data.jobs.length;

        const atsTypes = { greenhouse: 'Greenhouse', lever: 'Lever' };
        const jobsHtml = data.jobs.map(j => {
            const ats = atsTypes[j.source] || j.source || 'Generic';
            const atsBadge = `<span class="badge bg-secondary-subtle text-secondary">${ats}</span>`;
            const clBadge = j.has_cover_letter
                ? '<span class="badge bg-success-subtle text-success">CL Ready</span>'
                : '<span class="badge bg-warning-subtle text-warning">No CL</span>';
            return `
                <div class="border rounded p-2 mb-2 d-flex justify-content-between align-items-center">
                    <div>
                        <strong class="small">${escapeHtml(j.title)}</strong>
                        <span class="text-muted small"> at ${escapeHtml(j.company)}</span>
                    </div>
                    <div class="d-flex gap-1">${atsBadge} ${clBadge}</div>
                </div>`;
        }).join('');
        document.getElementById('af-jobs-list').innerHTML = jobsHtml;

        pendingAutofillIds = data.jobs.map(j => j.id);
        new bootstrap.Modal(document.getElementById('autofillPreviewModal')).show();
    } catch (err) {
        showToast('Failed to load preview', 'error');
    }
}

async function confirmAutofill() {
    if (pendingAutofillIds.length === 0) return;

    bootstrap.Modal.getInstance(document.getElementById('autofillPreviewModal')).hide();

    // Show progress bar
    document.getElementById('progress-container').style.display = 'block';
    document.getElementById('progress-label').textContent = 'Launching browser for auto-fill...';
    document.getElementById('progress-count').textContent = `0/${pendingAutofillIds.length}`;
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-detail').textContent = '';
    document.getElementById('btn-autofill').disabled = true;

    try {
        const resp = await fetch('/api/autofill', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_ids: pendingAutofillIds})
        });

        if (resp.status === 409) {
            showToast('Auto-fill already in progress', 'warning');
            document.getElementById('progress-container').style.display = 'none';
            return;
        }

        // Listen for SSE progress
        const evtSource = new EventSource('/api/autofill/progress');
        evtSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;

            document.getElementById('progress-bar').style.width = pct + '%';
            document.getElementById('progress-count').textContent = `${data.current}/${data.total}`;
            document.getElementById('progress-detail').textContent = data.message;
            document.getElementById('progress-label').textContent =
                data.status === 'done' ? 'Auto-fill complete' : 'Auto-filling applications...';

            if (data.status === 'done') {
                evtSource.close();
                setTimeout(() => {
                    document.getElementById('progress-container').style.display = 'none';
                    document.getElementById('btn-autofill').disabled = false;
                    showAutofillResults(data.results || []);
                    loadJobs(currentTab);
                    loadStats();
                }, 1000);
            }
        };

        evtSource.onerror = () => {
            evtSource.close();
            document.getElementById('progress-container').style.display = 'none';
            document.getElementById('btn-autofill').disabled = false;
            loadJobs(currentTab);
            loadStats();
        };

    } catch (err) {
        showToast('Failed to start auto-fill', 'error');
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('btn-autofill').disabled = false;
    }
}

function showAutofillResults(results) {
    if (results.length === 0) {
        showToast('Auto-fill complete. Close the browser when done submitting.', 'success');
        return;
    }

    let html = '<p class="text-muted small mb-3">Review the browser tabs and submit each application. Close the browser when done.</p>';

    results.forEach(r => {
        const statusIcon = r.status === 'filled'
            ? '<i class="bi bi-check-circle-fill text-success"></i>'
            : '<i class="bi bi-exclamation-circle-fill text-danger"></i>';

        const fieldsHtml = r.filled_fields && r.filled_fields.length > 0
            ? r.filled_fields.map(f => {
                const val = r.filled_details && r.filled_details[f] ? r.filled_details[f] : '';
                return `<div class="d-flex justify-content-between border-bottom py-1 small">
                    <span class="text-muted">${escapeHtml(f)}</span>
                    <span class="fw-medium">${escapeHtml(String(val))}</span>
                </div>`;
            }).join('')
            : '<span class="text-muted small">No fields filled</span>';

        html += `
            <div class="border rounded p-3 mb-2">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div>
                        ${statusIcon}
                        <strong class="ms-2">${escapeHtml(r.title)}</strong>
                        <span class="text-muted"> at ${escapeHtml(r.company)}</span>
                    </div>
                    <span class="badge bg-secondary-subtle text-secondary">${r.ats_type}</span>
                </div>
                <div class="bg-light rounded p-2">${fieldsHtml}</div>
            </div>`;
    });

    document.getElementById('autofill-results-body').innerHTML = html;
    new bootstrap.Modal(document.getElementById('autofillResultsModal')).show();
}
