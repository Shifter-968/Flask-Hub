(function () {
    function toTitleWords(value) {
        return value
            .replace(/[_-]+/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .replace(/\b\w/g, function (match) {
                return match.toUpperCase();
            });
    }

    function getFieldLabel(field) {
        if (field.id) {
            var explicitLabel = document.querySelector('label[for="' + field.id + '"]');
            if (explicitLabel && explicitLabel.textContent) {
                return explicitLabel.textContent.trim();
            }
        }

        var wrappingLabel = field.closest("label");
        if (wrappingLabel && wrappingLabel.textContent) {
            return wrappingLabel.textContent.trim();
        }

        var fromName = field.getAttribute("name") || field.getAttribute("id") || "value";
        return toTitleWords(fromName);
    }

    function descriptivePlaceholder(field) {
        var type = (field.type || "").toLowerCase();
        var label = getFieldLabel(field);

        if (type === "email") {
            return "Enter your email address (e.g. name@example.com)";
        }

        if (type === "password") {
            return "Enter a secure password";
        }

        if (field.tagName.toLowerCase() === "textarea") {
            return "Enter " + label.toLowerCase();
        }

        if (type === "number") {
            return "Enter " + label.toLowerCase();
        }

        return "Enter " + label.toLowerCase();
    }

    function shouldSkipPlaceholder(field) {
        var type = (field.type || "").toLowerCase();
        return ["hidden", "checkbox", "radio", "submit", "button", "file", "date", "time"].indexOf(type) !== -1;
    }

    function applyDescriptivePlaceholders() {
        var fields = document.querySelectorAll("form input, form textarea");
        fields.forEach(function (field) {
            if (shouldSkipPlaceholder(field)) {
                return;
            }

            var existing = (field.getAttribute("placeholder") || "").trim();
            if (!existing) {
                field.setAttribute("placeholder", descriptivePlaceholder(field));
            }
        });
    }

    function ensurePasswordRules(field) {
        field.setAttribute("minlength", "8");
        field.setAttribute("pattern", "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^A-Za-z0-9]).{8,}$");
        field.setAttribute(
            "title",
            "Password must be at least 8 characters and include an uppercase letter, lowercase letter, number, and special character."
        );
    }

    function addToggleButton(field) {
        if (field.dataset.toggleReady === "true") {
            return;
        }

        var wrapper = document.createElement("div");
        wrapper.className = "password-toggle-wrap";
        field.parentNode.insertBefore(wrapper, field);
        wrapper.appendChild(field);

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "password-toggle-btn";
        btn.textContent = "Show";
        btn.setAttribute("aria-label", "Show password");

        btn.addEventListener("click", function () {
            var isHidden = field.type === "password";
            field.type = isHidden ? "text" : "password";
            btn.textContent = isHidden ? "Hide" : "Show";
            btn.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
        });

        wrapper.appendChild(btn);
        field.dataset.toggleReady = "true";
    }

    function evaluatePasswordRules(value) {
        return {
            length: value.length >= 8,
            upper: /[A-Z]/.test(value),
            lower: /[a-z]/.test(value),
            number: /\d/.test(value),
            special: /[^A-Za-z0-9]/.test(value)
        };
    }

    function addPasswordChecklist(field) {
        if (field.dataset.hintReady === "true") {
            return;
        }

        var hint = document.createElement("div");
        hint.className = "password-requirement-hint";
        hint.innerHTML =
            "<div class='password-hint-title'>Password must include:</div>" +
            "<ul class='password-rule-list'>" +
            "<li data-rule='length'>At least 8 characters</li>" +
            "<li data-rule='upper'>An uppercase letter (A-Z)</li>" +
            "<li data-rule='lower'>A lowercase letter (a-z)</li>" +
            "<li data-rule='number'>A number (0-9)</li>" +
            "<li data-rule='special'>A special character (e.g. ! @ # $)</li>" +
            "</ul>";

        var parent = field.parentNode;
        if (parent && parent.classList && parent.classList.contains("password-toggle-wrap")) {
            if (parent.nextSibling) {
                parent.parentNode.insertBefore(hint, parent.nextSibling);
            } else {
                parent.parentNode.appendChild(hint);
            }
        } else if (field.nextSibling) {
            parent.insertBefore(hint, field.nextSibling);
        } else {
            parent.appendChild(hint);
        }

        var ruleItems = hint.querySelectorAll("li[data-rule]");
        var updateRules = function () {
            var status = evaluatePasswordRules(field.value || "");
            ruleItems.forEach(function (item) {
                var key = item.getAttribute("data-rule");
                var ok = !!status[key];
                item.classList.toggle("is-met", ok);
            });
        };

        field.addEventListener("input", updateRules);
        updateRules();

        field.dataset.hintReady = "true";
    }

    function applyPasswordEnhancements() {
        var passwordFields = document.querySelectorAll("form input[type='password']");
        passwordFields.forEach(function (field) {
            ensurePasswordRules(field);
            var existing = (field.getAttribute("placeholder") || "").trim();
            if (!existing) {
                field.setAttribute("placeholder", descriptivePlaceholder(field));
            }
            addToggleButton(field);
            addPasswordChecklist(field);
        });
    }

    function injectStyles() {
        if (document.getElementById("form-enhancement-styles")) {
            return;
        }

        var style = document.createElement("style");
        style.id = "form-enhancement-styles";
        style.textContent =
            ".password-toggle-wrap { position: relative; display: block; width: 100%; max-width: 100%; margin-bottom: 16px; }" +
            ".password-toggle-wrap input { width: 100%; padding-right: 72px; margin-bottom: 0 !important; }" +
            ".password-toggle-btn { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); border: 1px solid #cbd5e1; background: #f8fafc; border-radius: 8px; font-size: 0.78rem; padding: 6px 10px; cursor: pointer; color: #0f172a; }" +
            ".password-toggle-btn:hover { background: #eef2ff; }" +
            ".password-requirement-hint { display: block; margin: -6px 0 14px; color: #64748b; font-size: 0.78rem; line-height: 1.45; }" +
            ".password-hint-title { font-weight: 600; margin-bottom: 4px; color: #475569; }" +
            ".password-rule-list { margin: 0; padding-left: 18px; }" +
            ".password-rule-list li { color: #94a3b8; margin: 2px 0; }" +
            ".password-rule-list li.is-met { color: #16a34a; font-weight: 600; }" +
            ".hub-inline-input { min-width: 180px; }" +
            ".hub-table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; }" +
            ".hub-table-responsive > table { min-width: 620px; }";
        document.head.appendChild(style);
    }

    function applyControlClasses() {
        var selectors = "form input, form select, form textarea, form button";
        document.querySelectorAll(selectors).forEach(function (el) {
            var tag = el.tagName.toLowerCase();
            var type = (el.getAttribute("type") || "").toLowerCase();

            if (tag === "button" || type === "submit" || type === "button" || type === "reset") {
                if (!el.classList.contains("btn")) {
                    el.classList.add("btn");
                }
                if (!el.classList.contains("btn-primary") && !el.classList.contains("btn-outline-secondary")) {
                    el.classList.add("btn-primary");
                }
                return;
            }

            if (type === "checkbox" || type === "radio" || type === "hidden") {
                return;
            }

            if (!el.classList.contains("form-control") && !el.classList.contains("form-select")) {
                if (tag === "select") {
                    el.classList.add("form-select");
                } else {
                    el.classList.add("form-control");
                }
            }
        });
    }

    function makeTablesResponsive() {
        document.querySelectorAll("table").forEach(function (table) {
            var parent = table.parentElement;

            if (parent && (parent.classList.contains("table-responsive") || parent.classList.contains("hub-table-responsive"))) {
                return;
            }

            var wrapper = document.createElement("div");
            wrapper.className = "hub-table-responsive";
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        });
    }

    function initEnhancements() {
        injectStyles();
        applyDescriptivePlaceholders();
        applyPasswordEnhancements();
        applyControlClasses();
        makeTablesResponsive();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initEnhancements);
    } else {
        initEnhancements();
    }
})();
