;;; newton.el --- Upload and search NewtonEDMS from Emacs -*- lexical-binding: t; -*-

(require 'url)
(require 'json)

(defgroup newton nil "NewtonEDMS Emacs client." :group 'external)

(defcustom newton-base-url "http://127.0.0.1:8000"
  "NewtonEDMS server origin."
  :type 'string)

(defcustom newton-source-token ""
  "Anonymous source token for open upload."
  :type 'string)

(defun newton--post-file (path)
  "Upload PATH using the configured source token."
  (let ((url-request-method "POST")
        (boundary "----newtonemacs")
        (url-request-extra-headers
         '(("Content-Type" . "multipart/form-data; boundary=----newtonemacs")))
        (name (file-name-nondirectory path))
        (data (with-temp-buffer
                (set-buffer-multibyte nil)
                (insert-file-contents-literally path)
                (buffer-string))))
    (setq url-request-data
          (concat "--" boundary "\r\n"
                  "Content-Disposition: form-data; name=\"file\"; filename=\"" name "\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n"
                  data "\r\n"
                  "--" boundary "--\r\n"))
    (with-current-buffer
        (url-retrieve-synchronously
         (concat newton-base-url "/api/v1/open/upload/item/" newton-source-token))
      (goto-char (point-min))
      (re-search-forward "\n\n" nil t)
      (buffer-substring (point) (point-max)))))

(defun newton-upload-file (path)
  "Upload PATH to NewtonEDMS."
  (interactive "fFile: ")
  (message "%s" (newton--post-file path)))

(defun newton-search (query)
  "Run QUERY against NewtonEDMS (requires a logged-in cookie/session)."
  (interactive "sQuery: ")
  (with-current-buffer
      (url-retrieve-synchronously
       (concat newton-base-url "/api/query?q=" (url-hexify-string query)))
    (goto-char (point-min))
    (re-search-forward "\n\n" nil t)
    (let ((json-object-type 'alist))
      (pp (json-read)))))

(provide 'newton)
;;; newton.el ends here
