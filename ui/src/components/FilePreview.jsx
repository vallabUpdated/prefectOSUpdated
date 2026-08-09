export default function FilePreview({ filePreview }) {
  return (
    <div id="file-preview" className={filePreview ? "show" : ""}>
      {filePreview && (
        <>
          <div className="fp-header">
            <span className="fp-icon">⬡</span>
            <span className="fp-name">{filePreview.filename}</span>
          </div>
          <div className="fp-body">{filePreview.content}</div>
        </>
      )}
    </div>
  );
}
