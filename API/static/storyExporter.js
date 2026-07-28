/**
 * STORY EXPORTER (Helper Layer - File Downloads & Export Operations)
 * Handles downloading story chapters as TXT, Microsoft Word .doc, or Printing PDF.
 */
class StoryExporter {
    static safeFilename(title, fallback) {
        return title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim() || fallback;
    }

    static escapeHtml(text) {
        return text.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
    }

    static triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    static exportTxt(text, title = 'Chuong_truyen') {
        if (!text || !text.trim()) {
            alert("Chưa có nội dung để tải về.");
            return;
        }
        const filename = `${this.safeFilename(title, 'Chuong_truyen')}.txt`;
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        this.triggerDownload(blob, filename);
    }

    static exportDoc(text, title = 'Chương Truyện') {
        if (!text || !text.trim()) {
            alert("Chưa có nội dung để tải về.");
            return;
        }
        const safeTitle = this.escapeHtml(title);
        const htmlContent = `
            <html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
            <head><meta charset='utf-8'><title>${safeTitle}</title>
            <style>
                body { font-family: 'Times New Roman', serif; font-size: 13pt; line-height: 1.6; padding: 20px; }
                h1 { text-align: center; color: #1a1b28; margin-bottom: 20px; }
                p { text-indent: 1.5em; margin-bottom: 0.8em; text-align: justify; }
            </style>
            </head>
            <body>
                <h1>${safeTitle}</h1>
                ${text.split('\n\n').map(p => `<p>${this.escapeHtml(p).replace(/\n/g, '<br>')}</p>`).join('')}
            </body>
            </html>
        `;
        const filename = `${this.safeFilename(title, 'Chuong_truyen')}.doc`;
        const blob = new Blob(['\ufeff' + htmlContent], { type: 'application/msword' });
        this.triggerDownload(blob, filename);
    }

    static exportPdf(text) {
        if (!text || !text.trim()) {
            alert("Chưa có nội dung để tải về.");
            return;
        }
        window.print();
    }
}
