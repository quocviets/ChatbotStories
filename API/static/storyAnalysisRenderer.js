/**
 * STORY ANALYSIS RENDERER (UI Component Helper)
 * Handles rendering Quality Score, Issue Cards, and Vector Memory Summary HUD.
 */
class StoryAnalysisRenderer {
    static renderAnalysisResults(dom, analysis) {
        if (!dom || !analysis) return;
        dom.analysisIdle.classList.add('hidden');
        dom.analysisResults.classList.remove('hidden');
        dom.qualityScore.classList.remove('hidden');

        dom.qualityScore.innerText = `${analysis.score}/100`;
        dom.analysisStatusBadge.innerText = analysis.passed ? 'PASSED' : 'REVISION NEEDED';
        dom.analysisStatusBadge.className = `badge-status ${analysis.passed ? 'passed' : 'failed'}`;

        dom.issuesList.innerHTML = '';
        if (analysis.issues.length === 0) {
            dom.issuesList.innerHTML = '<div class="no-issues">✅ Không phát hiện lỗi bối cảnh nào.</div>';
        } else {
            analysis.issues.forEach(issue => {
                const card = document.createElement('div');
                card.className = `issue-item ${issue.severity.toLowerCase()}`;
                const header = document.createElement('div');
                header.className = 'issue-header';
                const severity = document.createElement('span');
                severity.className = 'severity-tag';
                severity.textContent = issue.severity;
                const type = document.createElement('span');
                type.className = 'issue-type';
                type.textContent = issue.type;
                header.append(severity, type);
                const description = document.createElement('div');
                description.className = 'issue-desc';
                description.textContent = issue.description;
                card.append(header, description);
                if (issue.suggested_action) {
                    const action = document.createElement('div');
                    action.className = 'issue-action';
                    action.textContent = `💡 Gợi ý: ${issue.suggested_action}`;
                    card.appendChild(action);
                }
                dom.issuesList.appendChild(card);
            });
        }
    }
}
