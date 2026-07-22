(function bootstrapCDMAgentRunner(global) {
  var RUNNER_VERSION = "0.0.22-query-clear";
  if (global.__CDMAgentRunner && global.__CDMAgentRunner.version === RUNNER_VERSION) {
    return;
  }

  var networkEvents = [];
  var networkWatcherInstalled = false;
  var debugOverlay = null;
  var queryObserverInstalled = false;
  var lastQueryEventText = "";
  var lastQueryEventAt = 0;

  function nowIso() {
    return new Date().toISOString();
  }

  function sleep(ms) {
    return new Promise(function(resolve) {
      global.setTimeout(resolve, ms);
    });
  }

  function waitFor(fn, timeout, interval) {
    var startedAt = Date.now();
    var max = timeout || 10000;
    var step = interval || 150;

    return new Promise(function(resolve, reject) {
      function check() {
        try {
          var value = fn();
          if (value) {
            resolve(value);
            return;
          }
        } catch (error) {}

        if (Date.now() - startedAt >= max) {
          reject(new Error("waitFor timeout"));
          return;
        }

        global.setTimeout(check, step);
      }

      check();
    });
  }

  function isVisible(node) {
    if (!node || !node.isConnected) {
      return false;
    }

    if (node.offsetParent !== null) {
      return true;
    }

    var style = global.getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  }

  function normalize(text) {
    var s = String(text || "").replace(/\s+/g, " ").trim();
    // NFC normalization handles Korean characters that look identical but have
    // different Unicode code points (e.g. composed vs. decomposed Hangul).
    return s.normalize ? s.normalize("NFC") : s;
  }

  function textOf(node) {
    return normalize(node.innerText || node.textContent || "");
  }

  function setNativeValue(element, value) {
    var proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (!descriptor || typeof descriptor.set !== "function") {
      element.value = value;
    } else {
      descriptor.set.call(element, value);
    }

    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function findReactPropsKey(el) {
    if (!el) return null;
    var keys = Object.getOwnPropertyNames(el);
    for (var i = 0; i < keys.length; i++) {
      if (keys[i].startsWith("__reactProps")) return keys[i];
    }
    return null;
  }

  function findReactFiberKey(el) {
    if (!el) return null;
    var keys = Object.getOwnPropertyNames(el);
    for (var i = 0; i < keys.length; i++) {
      if (keys[i].startsWith("__reactFiber") ||
          keys[i].startsWith("__reactInternalInstance")) {
        return keys[i];
      }
    }
    return null;
  }

  function notifyReactValueChange(element, value) {
    try {
    if (!element) return false;
    var event = {
      target: element,
      currentTarget: element,
      preventDefault: function() {},
      stopPropagation: function() {},
      isPropagationStopped: function() { return false; },
      nativeEvent: { isTrusted: true, type: "change", target: element },
      type: "change",
    };

    var propsKey = findReactPropsKey(element);
    if (propsKey) {
      var directProps = element[propsKey];
      if (directProps && typeof directProps.onChange === "function") {
        try { directProps.onChange(event, value); return true; } catch (e) {}
      }
      if (directProps && typeof directProps.onInput === "function") {
        try { directProps.onInput(Object.assign({}, event, { type: "input" }), value); return true; } catch (e) {}
      }
    }

    var fiberKey = findReactFiberKey(element);
    if (!fiberKey) return false;
    var node = element[fiberKey];
    for (var step = 0; node && step < 50; step++) {
      var props = node.memoizedProps || node.pendingProps;
      if (props) {
        if (typeof props.onChange === "function") {
          try { props.onChange(event, value); return true; } catch (e) {}
        }
        if (typeof props.onInput === "function") {
          try { props.onInput(Object.assign({}, event, { type: "input" }), value); return true; } catch (e) {}
        }
      }
      node = node.return;
    }
    return false;
    } catch (e) {
      return false;
    }
  }

  function clickNode(node) {
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "center", inline: "nearest" });
    }
    if (node && typeof node.focus === "function") {
      node.focus();
    }
    if (typeof global.PointerEvent === "function") {
      node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, view: global }));
      node.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true, view: global }));
    }
    node.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: global }));
    node.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: global }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: global }));
    if (typeof node.click === "function") {
      node.click();
    }
  }

  function clickPoint(x, y) {
    var target = document.elementFromPoint(x, y);
    if (!target) {
      return false;
    }

    clickNode(target);
    return true;
  }

  function findButtonExact(label) {
    return Array.prototype.slice
      .call(document.querySelectorAll("button, [role='button']"))
      .find(function(node) {
        return isVisible(node) && textOf(node) === label;
      });
  }

  function visibleTextNodes() {
    return Array.prototype.slice
      .call(document.querySelectorAll("th, td, div, span, label, button, a, h1, h2, h3"))
      .filter(isVisible)
      .filter(function(node) {
        return textOf(node);
      });
  }

  function uniqueVisibleTexts(limit) {
    var max = typeof limit === "number" ? limit : 120;
    return visibleTextNodes()
      .map(textOf)
      .filter(Boolean)
      .filter(function(value, index, array) {
        return array.indexOf(value) === index;
      })
      .slice(0, max);
  }

  function findVisibleTextNodeExact(label) {
    return visibleTextNodes().find(function(node) {
      return textOf(node) === label;
    });
  }

  function isNavNode(node) {
    return !!(node.closest && (
      node.closest("[role='navigation']") ||
      node.closest("nav") ||
      node.closest(".ms-Nav") ||
      node.closest(".ms-Nav-compositeLink") ||
      node.closest(".cr-nav-wrapped")
    ));
  }

  function findRow(rowLabel, anchorLabel, rowLabelOccurrence) {
    var allMatches = visibleTextNodes().filter(function(node) {
      return textOf(node) === rowLabel;
    });

    function controlsIn(node) {
      return node
        ? node.querySelectorAll("input, textarea, select, button, [role='button'], [tabindex]").length
        : 0;
    }

    function inputsIn(node) {
      return node
        ? node.querySelectorAll("input, textarea, select").length
        : 0;
    }

    function candidateRow(node) {
      if (!node) return null;
      return (
        node.closest("tr") ||
        node.parentElement && node.parentElement.closest("tr") ||
        node.closest(".item--wrapper") ||
        node.closest(".cr-section") ||
        node.parentElement
      );
    }

    var anchorBottom = null;
    if (anchorLabel) {
      try {
        var anchorRow = findRow(anchorLabel);
        var anchorRect = anchorRow && anchorRow.getBoundingClientRect ? anchorRow.getBoundingClientRect() : null;
        anchorBottom = anchorRect ? anchorRect.bottom : null;
      } catch (error) {}
    }

    var candidates = allMatches
      .filter(function(node) { return !isNavNode(node); })
      .map(function(node) {
        var row = candidateRow(node);
        var tr = node.closest("tr");
        var isHeader =
          (tr && tr.classList.contains("app-study-crf-group-header")) ||
          (node.closest && node.closest("thead"));
        var score = 0;
        if (row && inputsIn(row) > 0) score += 1000;
        if (row && controlsIn(row) > 0) score += 100;
        if (isHeader) score -= 500;
        if (anchorBottom !== null && row && row.getBoundingClientRect) {
          var rowRect = row.getBoundingClientRect();
          if (rowRect.top >= anchorBottom - 2) {
            score += 2000;
            score -= Math.max(0, rowRect.top - anchorBottom);
          } else {
            score -= 2000;
          }
        }
        return { node: node, row: row, score: score };
      })
      .sort(function(a, b) { return b.score - a.score; });

    var picked = candidates[0];
    var occurrence = parseInt(rowLabelOccurrence || 0, 10);
    if (occurrence > 1) {
      var occurrenceCandidates = candidates
        .filter(function(c) { return c.row && inputsIn(c.row) > 0; })
        .sort(function(a, b) {
          var ar = a.row.getBoundingClientRect ? a.row.getBoundingClientRect() : { top: 0 };
          var br = b.row.getBoundingClientRect ? b.row.getBoundingClientRect() : { top: 0 };
          return (ar.top || 0) - (br.top || 0);
        });
      if (occurrenceCandidates[occurrence - 1]) {
        picked = occurrenceCandidates[occurrence - 1];
      }
    }

    var labelNode = picked && picked.node;

    if (!labelNode) {
      throw new Error("Row label not found: " + rowLabel);
    }

    var row = picked && picked.row || candidateRow(labelNode);

    // app-study-crf-group-header is a section title row with no inputs.
    // Maven CDMS uses a separate <tbody> per section, so nextElementSibling of the
    // header <tr> is null. Walk the parent <tbody> chain instead.
    if (row && row.classList && row.classList.contains("app-study-crf-group-header")) {
      // 1) Same tbody — try sibling <tr>s
      var sibling = row.nextElementSibling;
      while (sibling) {
        if (sibling.querySelectorAll("input, textarea, select, button, [role='button'], [tabindex]").length > 0) {
          return sibling;
        }
        sibling = sibling.nextElementSibling;
      }
      // 2) Separate-tbody layout (Maven CDMS) — walk subsequent <tbody> elements
      var parentBody = row.parentElement;
      while (parentBody) {
        var nextBody = parentBody.nextElementSibling;
        if (!nextBody) break;
        var rows = nextBody.querySelectorAll("tr");
        for (var r = 0; r < rows.length; r++) {
          if (rows[r].querySelectorAll("input, textarea, select, button, [role='button']").length > 0) {
            return rows[r];
          }
        }
        parentBody = nextBody;
      }
    }

    return row;
  }

  function findHiddenRow(rowLabel) {
    var nodes = Array.prototype.slice
      .call(document.querySelectorAll("th, td, div, span, label"))
      .filter(function(node) {
        return textOf(node) === rowLabel && !isNavNode(node);
      });

    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var row = (
        node.closest("tr") ||
        node.parentElement && node.parentElement.closest("tr") ||
        node.closest(".item--wrapper") ||
        node.closest(".cr-section") ||
        node.parentElement
      );
      if (row && !isVisible(row)) {
        return row;
      }
    }
    return null;
  }

  function getRowTriggerState(rowLabel, action, anchorLabel, rowLabelOccurrence) {
    var row;
    try {
      row = findRow(rowLabel, anchorLabel, rowLabelOccurrence);
    } catch (error) {
      row = findHiddenRow(rowLabel);
      if (!row) {
        throw error;
      }
    }

    var rowVisible = isVisible(row);
    var controls = Array.prototype.slice.call(
      row.querySelectorAll("input, textarea, select, button, [role='button'], [role='radio'], [role='combobox'], [tabindex]")
    ).filter(function(node) {
      return isVisible(node) && node.type !== "hidden";
    });
    var dateTargets = Array.prototype.slice.call(
      row.querySelectorAll("i[data-icon-name='Calendar'], .GrDatePicker button, button, [role='button'], [tabindex='0']")
    ).filter(function(node) {
      if (!isVisible(node)) return false;
      var label = (node.getAttribute("aria-label") || "").toLowerCase();
      var hasSvg = node.querySelector && node.querySelector("svg") !== null;
      return label.includes("date") || label.includes("달력") || label.includes("calendar") || hasSvg;
    });
    var editableControls = controls.filter(function(node) {
      return !node.disabled && !node.readOnly && node.getAttribute("aria-disabled") !== "true";
    });
    var dateAvailable = action === "setDateViaCalendarPopup" && dateTargets.some(function(node) {
      return !node.disabled && node.getAttribute("aria-disabled") !== "true";
    });
    var rowAvailability = (editableControls.length > 0 || dateAvailable) ? "available" : "unavailable";
    var rowDisability = controls.length > 0 && editableControls.length === 0 && !dateAvailable ? "locked" : "unlocked";
    return {
      rowLabel: rowLabel,
      row: row,
      row_visibility: rowVisible ? "visible" : "hidden",
      row_availability: rowAvailability,
      row_disability: rowDisability,
      controls: controls.length,
      editableControls: editableControls.length,
      dateTargets: dateTargets.length,
    };
  }

  function skippedRowResult(action, state, reason) {
    return {
      action: action,
      outcome: "skipped",
      skipped: true,
      rowLabel: state.rowLabel,
      reason: reason,
      row_visibility: state.row_visibility,
      row_availability: state.row_availability,
      row_disability: state.row_disability,
    };
  }

  function rowSkipResult(rowLabel, action, anchorLabel, rowLabelOccurrence) {
    var state = getRowTriggerState(rowLabel, action, anchorLabel, rowLabelOccurrence);
    if (state.row_visibility === "hidden") {
      return skippedRowResult(action, state, "row_visibility_hidden");
    }
    if (state.row_availability === "unavailable") {
      return skippedRowResult(action, state, "row_availability_unavailable");
    }
    if (state.row_disability !== "unlocked") {
      return skippedRowResult(action, state, "row_disability_locked");
    }
    return null;
  }

  function findEditableInput(root) {
    var candidates = Array.prototype.slice.call(root.querySelectorAll("input, textarea"));
    var base = function(node) {
      return isVisible(node) && !node.disabled && !node.readOnly && node.type !== "hidden";
    };
    // Prefer inputs with a reachable tab stop; fall back to any editable input
    // (CDMS composite fields like "숫자 + 단위" may have tabIndex=-1 but still accept text)
    return (
      candidates.find(function(node) { return base(node) && node.tabIndex !== -1; }) ||
      candidates.find(function(node) { return base(node); })
    );
  }

  function comboboxTriggerCandidates(root) {
    var rootText = textOf(root);
    return Array.prototype.slice
      .call(
        root.querySelectorAll(
          "select, [role='combobox'], [aria-haspopup='listbox'], [aria-haspopup='menu'], button, input, [tabindex], .ant-select-selector, .MuiSelect-select, .MuiInputBase-root, .dropdown, .select, .picker"
        )
      )
      .filter(function(node) {
        return isVisible(node) && !node.disabled && node.getAttribute("aria-disabled") !== "true";
      })
      .map(function(node) {
        var score = 0;
        var label = textOf(node);
        var className = String(node.className || "");
        var rect = node.getBoundingClientRect ? node.getBoundingClientRect() : { right: 0, width: 0 };

        if (node.tagName === "SELECT") score += 100;
        if (node.getAttribute("role") === "combobox") score += 90;
        if (node.getAttribute("aria-haspopup") === "listbox" || node.getAttribute("aria-haspopup") === "menu") score += 70;
        if (node.tagName === "BUTTON") score += 50;
        if (node.tagName === "INPUT") score += 40;
        if (node.tagName === "SVG" || node.tagName === "I") score += 35;
        if (/select|dropdown|picker|combo/i.test(className)) score += 40;
        if (/icon|chevron|arrow/i.test(className)) score += 35;
        if (label && label !== rootText) score += 20;
        if (/선택/.test(label)) score += 20;
        if (node.querySelector && node.querySelector("svg, i, [data-icon-name], [aria-hidden='true']")) score += 20;
        if (rect.right > 0) score += Math.min(20, Math.round(rect.right / 100));
        if (rect.width > 0) score += Math.min(20, Math.round(rect.width / 80));
        if (node === root || label === rootText) score -= 120;

        return { node: node, score: score };
      })
      .sort(function(left, right) {
        return right.score - left.score;
      })
      .map(function(entry) {
        return entry.node;
      });
  }

  function rightEdgeClickTargets(root) {
    var targets = [];
    var rowRect = root.getBoundingClientRect ? root.getBoundingClientRect() : null;
    if (rowRect && rowRect.width > 40 && rowRect.height > 10) {
      targets.push({
        type: "point",
        x: Math.max(rowRect.left + 10, rowRect.right - 24),
        y: rowRect.top + rowRect.height / 2,
      });
    }

    Array.prototype.slice
      .call(root.querySelectorAll("svg, i, [data-icon-name], [aria-hidden='true']"))
      .filter(isVisible)
      .forEach(function(node) {
        targets.push({ type: "node", node: node });
      });

    return targets;
  }

  function findComboboxTrigger(root) {
    return comboboxTriggerCandidates(root).find(function(node) {
      return node;
    });
  }

  function optionHost(node) {
    if (!node) {
      return null;
    }

    return (
      node.closest("[role='option']") ||
      node.closest("li") ||
      node.closest(".ant-select-item-option") ||
      node.closest(".MuiMenuItem-root") ||
      node.closest(".MuiAutocomplete-option") ||
      node
    );
  }

  function normalizedIncludes(source, target) {
    var left = normalize(source);
    var right = normalize(target);
    return !!left && !!right && left.indexOf(right) >= 0;
  }

  function isSaveEnabled() {
    var saveButton = findButtonExact("Save");
    return !!saveButton && !saveButton.disabled && saveButton.getAttribute("aria-disabled") !== "true";
  }

  function waitForComboboxCommit(rowLabel, optionLabel, beforeRowText, beforeRows) {
    return waitFor(function() {
      var row = findRow(rowLabel);
      var rowText = textOf(row);
      var rows = visibleRows();
      var revealedNewRow = rows.some(function(label) {
        return beforeRows.indexOf(label) < 0;
      });
      var textChanged = normalize(rowText) !== normalize(beforeRowText);
      var placeholderGone = rowText.indexOf("선택해주세요") < 0;
      var showsOption = normalizedIncludes(rowText, optionLabel) || normalizedIncludes(optionLabel, rowText);
      return showsOption || (textChanged && placeholderGone) || revealedNewRow || isSaveEnabled();
    }, 8000, 150);
  }

  function popupOptionCandidates() {
    return Array.prototype.slice
      .call(
        document.querySelectorAll(
          "[role='option'], [role='menuitem'], [role='listbox'] [role='presentation'], li, .ant-select-item-option, .MuiMenuItem-root, .MuiAutocomplete-option"
        )
      )
      .filter(isVisible)
      .filter(function(node) {
        return textOf(node);
      });
  }

  function findPopupOption(optionLabel) {
    var popupCandidate = popupOptionCandidates().find(function(node) {
      var text = textOf(node);
      return text === optionLabel || normalizedIncludes(text, optionLabel) || normalizedIncludes(optionLabel, text);
    });
    if (popupCandidate) {
      return popupCandidate;
    }

    return visibleTextNodes().find(function(node) {
      var text = textOf(node);
      return text === optionLabel || normalizedIncludes(text, optionLabel) || normalizedIncludes(optionLabel, text);
    });
  }

  function addNetworkEvent(event) {
    networkEvents.push({
      url: event.url || "",
      method: event.method || "GET",
      status: event.status,
      ok: event.ok,
      responseExcerpt: event.responseExcerpt || "",
      timestamp: nowIso(),
    });

    if (networkEvents.length > 200) {
      networkEvents.shift();
    }
  }

  function installNetworkWatcher() {
    if (networkWatcherInstalled) {
      return;
    }

    networkWatcherInstalled = true;

    if (typeof global.fetch === "function") {
      var originalFetch = global.fetch.bind(global);
      global.fetch = function(input, init) {
        return originalFetch(input, init).then(function(response) {
          var url = typeof input === "string" ? input : input && input.url;
          var method = init && init.method ? init.method : "GET";
          try {
            response.clone().text().then(function(text) {
              addNetworkEvent({
                url: url,
                method: method,
                status: response.status,
                ok: response.ok,
                responseExcerpt: String(text || "").slice(0, 1000),
              });
            });
          } catch (error) {
            addNetworkEvent({ url: url, method: method, status: response.status, ok: response.ok });
          }

          return response;
        });
      };
    }

    if (global.XMLHttpRequest) {
      var originalOpen = global.XMLHttpRequest.prototype.open;
      var originalSend = global.XMLHttpRequest.prototype.send;

      global.XMLHttpRequest.prototype.open = function(method, url) {
        this.__cdmAgentMethod = method;
        this.__cdmAgentUrl = url;
        return originalOpen.apply(this, arguments);
      };

      global.XMLHttpRequest.prototype.send = function(body) {
        this.addEventListener("load", function() {
          addNetworkEvent({
            url: this.__cdmAgentUrl,
            method: this.__cdmAgentMethod,
            status: this.status,
            ok: this.status >= 200 && this.status < 400,
            responseExcerpt: String(this.responseText || "").slice(0, 1000),
          });
        });
        return originalSend.apply(this, arguments);
      };
    }
  }

  function toastTexts() {
    return Array.prototype.slice
      .call(document.querySelectorAll("[role='alert'], [aria-live], .Toastify__toast, .MuiSnackbar-root, .MuiAlert-root"))
      .filter(isVisible)
      .map(textOf)
      .filter(Boolean);
  }

  function modalTexts() {
    return Array.prototype.slice
      .call(document.querySelectorAll("[role='dialog'], .MuiPopover-root, .MuiModal-root, .MuiPaper-root"))
      .filter(isVisible)
      .map(textOf)
      .filter(Boolean);
  }

  function inferRowLabelFromInvalidNode(node) {
    var row = node.closest("tr") || node.closest(".item--wrapper") || node.parentElement;
    if (!row) {
      return null;
    }

    var candidate = Array.prototype.slice
      .call(row.querySelectorAll("th, td, div, span, label"))
      .filter(isVisible)
      .map(textOf)
      .find(function(text) {
        return text && text !== "Save" && text !== "Save & Next";
      });

    return candidate || null;
  }

  function collectValidationSignals() {
    var invalidNodes = Array.prototype.slice.call(document.querySelectorAll("[aria-invalid='true']"));
    var invalidRowLabels = invalidNodes
      .map(inferRowLabelFromInvalidNode)
      .filter(Boolean)
      .filter(function(value, index, array) {
        return array.indexOf(value) === index;
      });

    var buttons = Array.prototype.slice
      .call(document.querySelectorAll("button"))
      .filter(isVisible)
      .map(function(button) {
        return {
          label: textOf(button),
          disabled: !!button.disabled || button.getAttribute("aria-disabled") === "true",
        };
      })
      .filter(function(button) {
        return button.label;
      });

    return {
      invalidCount: invalidNodes.length,
      invalidRowLabels: invalidRowLabels,
      toastTexts: toastTexts(),
      modalTexts: modalTexts(),
      buttonStates: buttons,
    };
  }

  function queryRows() {
    var texts = uniqueVisibleTexts(300);
    Array.prototype.slice
      .call(document.querySelectorAll("td.message, .message-inner, [class*='message']"))
      .filter(isVisible)
      .map(textOf)
      .filter(function(text) {
        return text && text.indexOf("Query [") >= 0;
      })
      .forEach(function(text) {
        texts.push(text);
      });
    Array.prototype.slice
      .call(document.querySelectorAll("[role='alert'], [class*='error'], [class*='invalid'], [class*='validation']"))
      .filter(isVisible)
      .map(textOf)
      .filter(Boolean)
      .forEach(function(text) {
        texts.push(text);
      });

    return texts
      .filter(function(text) {
        return text.indexOf("Query [") >= 0;
      })
      .map(function(text) {
        var idx = text.indexOf("Query [");
        return idx >= 0 ? text.slice(idx) : text;
      })
      .filter(function(value, index, array) {
        return array.indexOf(value) === index;
      });
  }

  function queryLabelMatches(text, label) {
    var normalizedText = normalize(text);
    var normalizedLabel = normalize(label);
    if (!normalizedText || !normalizedLabel) return false;
    return normalizedText.indexOf("query[" + normalizedLabel + "]") >= 0
      || normalizedText.indexOf(normalizedLabel) >= 0;
  }

  function findQueryMessageRow(label) {
    var nodes = Array.prototype.slice.call(document.querySelectorAll("td.message, .message-inner, [class*='message']"))
      .filter(function(node) {
        var text = textOf(node);
        return text.indexOf("Query [") >= 0 && (!label || queryLabelMatches(text, label));
      });
    if (!nodes.length) return null;
    return nodes[0].closest("tr") || nodes[0];
  }

  function queryActionCandidates(row) {
    if (!row) return [];
    var cells = Array.prototype.slice.call(row.querySelectorAll(":scope > td, :scope > th"));
    var messageCellIndex = cells.findIndex(function(cell) {
      return textOf(cell).indexOf("Query [") >= 0;
    });
    var roots = messageCellIndex >= 0 ? cells.slice(messageCellIndex + 1) : [row];
    var out = [];
    roots.forEach(function(root) {
      Array.prototype.slice.call(root.querySelectorAll("button, [role='button'], svg, i, span, div"))
        .forEach(function(node) {
          if (!isVisible(node)) return;
          var rect = node.getBoundingClientRect();
          if (rect.width < 6 || rect.height < 6) return;
          var label = [
            node.getAttribute("aria-label") || "",
            node.getAttribute("title") || "",
            node.getAttribute("data-icon-name") || "",
            textOf(node),
          ].join(" ");
          out.push({ node: node, label: label, rect: rect });
        });
    });
    var seen = new Set();
    return out.filter(function(item) {
      var key = [Math.round(item.rect.left), Math.round(item.rect.top), Math.round(item.rect.width), Math.round(item.rect.height)].join(":");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function getQueryActionCoords(label, actionName) {
    var row = findQueryMessageRow(label);
    if (!row) return null;
    var action = normalize(actionName || "cancel");
    var candidates = queryActionCandidates(row);
    if (!candidates.length) return null;
    function score(item, index) {
      var text = normalize(item.label);
      var value = 0;
      if (action === "accept" || action === "resolve" || action === "check") {
        if (/(check|done|accept|resolve|confirm|확인|승인|완료)/i.test(item.label)) value += 100;
        if (index === 1) value += 20;
      } else if (action === "refresh") {
        if (/(refresh|reload|reset|새로|초기화)/i.test(item.label)) value += 100;
        if (index === 3) value += 20;
      } else {
        if (/(close|cancel|delete|remove|clear|dismiss|x|취소|닫기|삭제|제거)/i.test(item.label)) value += 100;
        if (text === "x" || text === "×") value += 80;
        if (index === 2) value += 20;
      }
      return value;
    }
    var selected = candidates.map(function(item, index) {
      return { item: item, score: score(item, index) };
    }).sort(function(a, b) {
      return b.score - a.score;
    })[0].item.node;
    selected.scrollIntoView({ block: "center", inline: "nearest" });
    var rect = selected.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  async function clickQueryAction(label, actionName) {
    var coords = getQueryActionCoords(label, actionName || "cancel");
    if (!coords) {
      return { action: "clickQueryAction", outcome: "not_found", label: label || "", queryAction: actionName || "cancel" };
    }
    var node = document.elementFromPoint(coords.x, coords.y);
    if (!node) {
      return { action: "clickQueryAction", outcome: "not_found", label: label || "", queryAction: actionName || "cancel" };
    }
    humanClick(node);
    await sleep(250);
    return { action: "clickQueryAction", outcome: "clicked", label: label || "", queryAction: actionName || "cancel" };
  }

  function emitQueryEvents() {
    if (!global.chrome || !global.chrome.runtime || typeof global.chrome.runtime.sendMessage !== "function") {
      return;
    }
    queryRows().forEach(function(text) {
      var normalizedText = normalize(text);
      var now = Date.now();
      if (!normalizedText || (normalizedText === lastQueryEventText && now - lastQueryEventAt < 1000)) {
        return;
      }
      lastQueryEventText = normalizedText;
      lastQueryEventAt = now;
      try {
        global.chrome.runtime.sendMessage({
          type: "query-event",
          payload: {
            text: text,
            url: global.location.href,
            pathname: global.location.pathname,
            pageLabel: activePageInfo().pageLabel,
            timestamp: nowIso(),
          },
        });
      } catch (error) {}
    });
  }

  function installQueryObserver() {
    if (queryObserverInstalled || typeof MutationObserver !== "function") {
      return;
    }
    queryObserverInstalled = true;
    var pending = false;
    var observer = new MutationObserver(function() {
      if (pending) return;
      pending = true;
      global.setTimeout(function() {
        pending = false;
        emitQueryEvents();
      }, 50);
    });
    observer.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    global.setTimeout(emitQueryEvents, 100);
  }

  function queryMatchesLabels(text, labels) {
    if (!labels || !labels.length) {
      return true;
    }
    var normalizedText = normalize(text).replace(/\s+/g, "").toLowerCase();
    return labels.some(function(label) {
      var normalizedLabel = normalize(label).replace(/\s+/g, "").toLowerCase();
      return normalizedLabel && (
        normalizedText.indexOf("query[" + normalizedLabel + "]") >= 0 ||
        normalizedText.indexOf(normalizedLabel) >= 0
      );
    });
  }

  function waitForQueryMessages(labels, timeoutMs) {
    var wantedLabels = (labels || []).filter(Boolean);
    var timeout = typeof timeoutMs === "number" ? timeoutMs : 3000;
    var startedAt = Date.now();

    return new Promise(function(resolve) {
      function currentMatches() {
        return queryRows().filter(function(text) {
          return queryMatchesLabels(text, wantedLabels);
        });
      }

      var initial = currentMatches();
      if (initial.length) {
        resolve({ outcome: "query_observed", queryRows: initial, elapsedMs: Date.now() - startedAt });
        return;
      }

      var done = false;
      var observer = new MutationObserver(function() {
        if (done) return;
        var matches = currentMatches();
        if (!matches.length) return;
        done = true;
        observer.disconnect();
        resolve({ outcome: "query_observed", queryRows: matches, elapsedMs: Date.now() - startedAt });
      });

      observer.observe(document.documentElement || document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      });

      global.setTimeout(function() {
        if (done) return;
        done = true;
        observer.disconnect();
        resolve({ outcome: "no_query_observed", queryRows: [], elapsedMs: Date.now() - startedAt });
      }, timeout);
    });
  }

  function visibleRows() {
    return Array.prototype.slice
      .call(document.querySelectorAll("th, label, .item-label, .app-study-crf-group-header, .cr-section-title"))
      .filter(isVisible)
      .map(textOf)
      .filter(Boolean)
      .filter(function(value, index, array) {
        return array.indexOf(value) === index;
      });
  }

  function structuredRows() {
    var optionLikeLabels = [
      "예", "아니요", "남성", "여성", "기타",
      "Tumor", "Nodes", "Metastasis", "Stage",
      "흡연 중", "금연 중", "흡연력 없음",
      "음주 중", "금주 중", "음주력 없음",
      "유방확대술", "유방재건술", "해당사항 없음",
      "[Select ..]"
    ];

    function isOptionLike(text) {
      var value = normalize(text);
      return !value || optionLikeLabels.indexOf(value) >= 0 || value.indexOf("Query [") === 0;
    }

    function controlsIn(root) {
      return Array.prototype.slice.call(root.querySelectorAll(
        "input, textarea, select, button, [role='radio'], [role='combobox'], [aria-haspopup='listbox'], [aria-haspopup='menu'], [tabindex]"
      )).filter(function(node) {
        return isVisible(node) && node.type !== "hidden";
      });
    }

    function rowForControl(control) {
      return (
        control.closest("tr") ||
        control.closest(".item--wrapper") ||
        control.closest("[class*='field']") ||
        control.closest(".cr-section") ||
        control.parentElement
      );
    }

    function isHeaderRow(row) {
      return !!(row && (
        row.closest && row.closest("thead") ||
        row.classList && row.classList.contains("app-study-crf-group-header") ||
        row.querySelectorAll("input, textarea, select, button, [role='radio'], [role='combobox']").length === 0
      ));
    }

    function controlTypeFor(row) {
      if (row.querySelector("input[type='radio'], [role='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) return "radio";
      if (row.querySelector("input[type='checkbox']")) return "checkbox";
      if (row.querySelector("i[data-icon-name='Calendar'], .GrDatePicker button")) return "date";
      if (row.querySelector("textarea")) return "textarea";
      if (row.querySelector("select, [role='combobox'], [aria-haspopup='listbox'], [aria-haspopup='menu']")) return "select";
      if (row.querySelector("input")) return "input";
      return "unknown";
    }

    function rowOptions(row) {
      return Array.prototype.slice
        .call(row.querySelectorAll("label, [role='radio'], button, span"))
        .filter(isVisible)
        .map(textOf)
        .filter(function(text) {
          return text && text.length <= 80 && !text.includes("→");
        })
        .filter(function(value, index, array) {
          return array.indexOf(value) === index;
        });
    }

    function inputDetails(row) {
      return Array.prototype.slice.call(row.querySelectorAll("input, textarea, select")).map(function(node) {
        return {
          tag: (node.tagName || "").toLowerCase(),
          type: node.getAttribute("type") || "",
          value: node.value || "",
          placeholder: node.getAttribute("placeholder") || "",
          disabled: !!node.disabled,
          readOnly: !!node.readOnly,
          visible: isVisible(node),
          ariaLabel: node.getAttribute("aria-label") || "",
        };
      });
    }

    function buttonDetails(row) {
      return Array.prototype.slice.call(row.querySelectorAll("button, [role='button'], [tabindex='0']")).map(function(node) {
        return {
          tag: (node.tagName || "").toLowerCase(),
          text: textOf(node),
          ariaLabel: node.getAttribute("aria-label") || "",
          disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
          visible: isVisible(node),
          hasSvg: !!(node.querySelector && node.querySelector("svg")),
        };
      });
    }

    function rowLabel(row) {
      var cells = Array.prototype.slice.call(row.querySelectorAll(":scope > th, :scope > td"));
      if (cells.length) {
        var first = textOf(cells[0]);
        if (first && !isOptionLike(first)) return first;
        if (cells.length > 1 && isOptionLike(first)) {
          var table = row.closest("table");
          var index = cells.indexOf(cells.find(function(cell) {
            return controlsIn(cell).length > 0;
          }));
          var columnHeader = "";
          if (table && index >= 0) {
            var headerRows = Array.prototype.slice.call(table.querySelectorAll("thead tr, tr")).filter(function(tr) {
              return tr !== row && tr.querySelectorAll("th").length > 0;
            });
            for (var h = headerRows.length - 1; h >= 0; h--) {
              var headers = Array.prototype.slice.call(headerRows[h].querySelectorAll("th, td"));
              if (headers[index]) {
                columnHeader = textOf(headers[index]);
                if (columnHeader) break;
              }
            }
          }
          if (first && columnHeader && !isOptionLike(columnHeader)) {
            return first + " / " + columnHeader;
          }
          if (columnHeader && !isOptionLike(columnHeader)) return columnHeader;
        }
      }
      var label = Array.prototype.slice
        .call(row.querySelectorAll(".item-label, label, th, td"))
        .filter(isVisible)
        .map(textOf)
        .find(function(text) {
          return text && !isOptionLike(text) && text.length <= 120;
        });
      return label || "";
    }

    var controls = Array.prototype.slice.call(document.querySelectorAll(
      "input, textarea, select, button, [role='radio'], [role='combobox'], [aria-haspopup='listbox'], [aria-haspopup='menu']"
    )).filter(function(node) {
      return isVisible(node) && node.type !== "hidden";
    });

    var rows = controls
      .map(rowForControl)
      .filter(function(row) {
        return row && isVisible(row) && !isHeaderRow(row);
      })
      .filter(function(value, index, array) {
        return array.indexOf(value) === index;
      });

    return rows
      .map(function(row) {
        var label = rowLabel(row);
        if (!label) return null;
        var controls = controlsIn(row);
        var editableControls = controls.filter(function(node) {
          return isVisible(node) && !node.disabled && !node.readOnly && node.getAttribute("aria-disabled") !== "true" && node.type !== "hidden";
        });
        var controlType = controlTypeFor(row);
        var rowVisible = isVisible(row);
        var rowAvailability = rowVisible && editableControls.length > 0 ? "available" : "unavailable";
        var rowDisability = controls.length > 0 && editableControls.length === 0 ? "locked" : "unlocked";
        return {
          rowLabel: label,
          visible: rowVisible,
          editable: rowVisible && editableControls.length > 0,
          disabled: controls.length > 0 && editableControls.length === 0,
          row_visibility: rowVisible ? "visible" : "hidden",
          row_availability: rowAvailability,
          row_disability: rowDisability,
          controlType: controlType,
          options: controlType === "radio" || controlType === "checkbox"
            ? rowOptions(row).filter(function(text) { return text !== label && !text.includes("→"); })
            : [],
          inputs: inputDetails(row),
          buttons: buttonDetails(row),
        };
      })
      .filter(Boolean)
      .filter(function(row, index, array) {
        return array.findIndex(function(other) { return other.rowLabel === row.rowLabel; }) === index;
      });
  }

  function activePageLabel() {
    return activePageInfo().label;
  }

  function activePageInfo() {
    var crfTitle = Array.prototype.slice
      .call(document.querySelectorAll(".cr-section-title, .cr-section-header, .app-study-crf-group-header"))
      .find(function(node) {
        return isVisible(node) && textOf(node) && !textOf(node).includes("Query [");
      });

    if (crfTitle) {
      var title = textOf(crfTitle);
      return { label: title, rawLabel: title, statusNumbers: [] };
    }

    var activeSidebar = Array.prototype.slice
      .call(document.querySelectorAll("nav [aria-current='page'], nav .active, nav .selected, nav .is-active, .cr-nav-wrapped [aria-current='page'], .cr-nav-wrapped .active, .cr-nav-wrapped .selected, .cr-nav-wrapped .is-active"))
      .find(function(node) {
        return isVisible(node) && textOf(node);
      });

    if (activeSidebar) {
      var raw = textOf(activeSidebar);
      var match = raw.match(/^((?:\d+\s+)+)(.+)$/);
      var statusNumbers = match ? match[1].trim().split(/\s+/).map(function(value) { return Number(value); }) : [];
      return {
        label: match ? match[2].trim() : raw,
        rawLabel: raw,
        statusNumbers: statusNumbers,
      };
    }

    var heading = Array.prototype.slice.call(document.querySelectorAll("h1, h2, h3")).find(function(node) {
      return isVisible(node) && textOf(node);
    });

    var label = heading ? textOf(heading) : "";
    return { label: label, rawLabel: label, statusNumbers: [] };
  }

  function inspectActivePage() {
    var signals = collectValidationSignals();
    var pageInfo = activePageInfo();
    var observedQueryRows = queryRows();
    return {
      url: global.location.href,
      pathname: global.location.pathname,
      pageLabel: pageInfo.label,
      rawPageLabel: pageInfo.rawLabel,
      pageStatus: {
        rawLabel: pageInfo.rawLabel,
        statusNumbers: pageInfo.statusNumbers,
        queryCount: observedQueryRows.length,
        invalidCount: signals.invalidCount,
      },
      visibleRows: visibleRows(),
      structuredRows: structuredRows(),
      enabledActions: signals.buttonStates.filter(function(button) {
        return !button.disabled;
      }).map(function(button) {
        return button.label;
      }),
      invalidRowLabels: signals.invalidRowLabels,
      invalidCount: signals.invalidCount,
      queryRows: observedQueryRows,
      queryCount: observedQueryRows.length,
      buttonStates: signals.buttonStates,
      toastTexts: signals.toastTexts,
      modalTexts: signals.modalTexts,
      visibleTextSamples: uniqueVisibleTexts(),
      timestamp: nowIso(),
    };
  }

  function capturePage() {
    return inspectActivePage();
  }

  function listNavPages() {
    var seen = {};
    var pages = [];

    // Maven CDMS SPA renders nav items as <a href> via React Router.
    // Collect ALL anchor elements regardless of class.
    var allAnchors = Array.prototype.slice.call(document.querySelectorAll("a"));
    allAnchors.forEach(function(el) {
      var href = el.href || el.getAttribute("href") || "";
      if (!href || href === "#" || href.indexOf("javascript") === 0) return;
      try {
        var pathname = new URL(href, global.location.href).pathname;
        // Match: /s/{study}/subjects/{subject}/{visitType}/{visitId}/{n}/{pageId}/{n}
        var m = pathname.match(/\/subjects\/[^/]+\/[A-Z]+\/([A-Z0-9]+)\/\d+\/([A-Z0-9]+)\/\d+$/);
        if (!m) return;
        var visitId = m[1];
        var pageId = m[2];
        var key = visitId + "/" + pageId;
        if (seen[key]) return;
        seen[key] = true;
        var label = normalize(el.innerText || el.textContent || pageId);
        pages.push({ pageId: pageId, visitId: visitId, label: label, pathname: pathname });
      } catch (e) {}
    });

    return { pages: pages, currentPathname: global.location.pathname };
  }

  async function setText(rowLabel, value) {
    var skip = rowSkipResult(rowLabel, "setText");
    if (skip) return skip;
    var row = findRow(rowLabel);
    var input = findEditableInput(row);
    if (!input) {
      throw new Error("Editable input not found for row: " + rowLabel);
    }

    input.focus();
    clickNode(input);
    setNativeValue(input, value || "");
    await sleep(250);

    return {
      rowLabel: rowLabel,
      value: input.value,
      action: "setText",
    };
  }

  async function setDateViaCalendarPopup(rowLabel, value) {
    // If a date-popup input is already open, use it directly (re-entry / manual open)
    var existingPopup = Array.prototype.slice.call(document.querySelectorAll("input")).find(function(n) {
      return isVisible(n) && n.placeholder === "YYYY-MM-DD";
    });
    if (existingPopup) {
      setNativeValue(existingPopup, value || "");
      notifyReactValueChange(existingPopup, value || "");
      await sleep(100);
      var preEnter = findButtonExact("Enter");
      if (preEnter) { clickNode(preEnter); await sleep(400); }
      return { rowLabel: rowLabel, value: value, action: "setDateViaCalendarPopup" };
    }

    var row = findRow(rowLabel);
    var skip = rowSkipResult(rowLabel, "setDateViaCalendarPopup");
    if (skip) return skip;

    // Fluent i[data-icon-name='Calendar'] — standard Fluent DatePicker
    // GrIcon / GrDatePicker button — Maven CDMS custom date picker
    var icon = row.querySelector("i[data-icon-name='Calendar']")
      || row.querySelector(".GrDatePicker button")
      || Array.prototype.slice.call(
          row.querySelectorAll("button, [role='button'], [tabindex='0']")
        ).find(function(el) {
          var label = (el.getAttribute("aria-label") || "").toLowerCase();
          var hasSvg = el.querySelector("svg") !== null;
          return label.includes("date") || label.includes("달력") || label.includes("calendar") || hasSvg;
        });

    var fallbackInput = Array.prototype.slice.call(row.querySelectorAll("input")).find(function(node) {
      return isVisible(node) && node.type !== "hidden";
    });

    if (!icon && !fallbackInput) {
      throw new Error("Calendar icon not found for row: " + rowLabel);
    }

    async function commitDateInput(input) {
      if (!input) return false;
      try { input.readOnly = false; } catch (e) {}
      clickNode(input);
      setNativeValue(input, value || "");
      notifyReactValueChange(input, value || "");
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.dispatchEvent(new Event("blur", { bubbles: true }));
      await sleep(500);
      return input.value === value;
    }

    if (await commitDateInput(fallbackInput)) {
      return {
        rowLabel: rowLabel,
        value: fallbackInput.value,
        action: "setDateViaCalendarPopup",
      };
    }

    if (icon) {
      clickNode(icon);
      await sleep(250);

      try {
        var popupInput = await waitFor(function() {
          return Array.prototype.slice.call(document.querySelectorAll("input")).find(function(node) {
            return isVisible(node) && node.placeholder === "YYYY-MM-DD";
          });
        }, 2000, 100);

        setNativeValue(popupInput, value || "");
        notifyReactValueChange(popupInput, value || "");
        await sleep(100);

        var enterButton = findButtonExact("Enter");
        if (!enterButton) {
          throw new Error("Date popup Enter button not found.");
        }

        clickNode(enterButton);
        await sleep(400);
      } catch (error) {}
    }

    if (fallbackInput) {
      await commitDateInput(fallbackInput);
    }

    var mainInput = Array.prototype.slice.call(row.querySelectorAll("input")).find(function(node) {
      return isVisible(node);
    });

    if (mainInput && mainInput.value !== value) {
      await commitDateInput(mainInput);
    }

    mainInput = Array.prototype.slice.call(row.querySelectorAll("input")).find(function(node) {
      return isVisible(node);
    });

    if (!mainInput || mainInput.value !== value) {
      throw new Error("Date value was not committed for row " + rowLabel + ": expected " + value + ", actual " + (mainInput ? mainInput.value : "<none>"));
    }

    return {
      rowLabel: rowLabel,
      value: mainInput ? mainInput.value : value,
      action: "setDateViaCalendarPopup",
    };
  }

  async function selectRadio(rowLabel, optionLabel, anchorLabel, probeOnly, rowLabelOccurrence) {
    var skip = rowSkipResult(rowLabel, "selectRadio", anchorLabel, rowLabelOccurrence);
    if (skip) return skip;
    function pageContainsValidationQuery(targetRowLabel) {
      // Check whether CDMS is still showing a validation error for this row.
      // We look for the row label inside known validation-message containers rather
      // than matching the exact (locale-dependent) Korean message text.
      var label = normalize(targetRowLabel);
      return Array.prototype.slice
        .call(document.querySelectorAll("[class*='error'], [class*='invalid'], [class*='validation'], [role='alert']"))
        .filter(isVisible)
        .some(function(el) {
          return normalize(el.textContent || "").indexOf(label) >= 0;
        });
    }

    function radioSelectionSatisfied(targetRowLabel, targetOptionLabel, targetAnchorLabel) {
      var row = null;
      try {
        row = findRow(targetRowLabel, targetAnchorLabel, rowLabelOccurrence);
      } catch (error) {}

      var searchRoot = row || document;
      var radioNodes = Array.prototype.slice.call(
        searchRoot.querySelectorAll("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox'], [role='radio'], label, button, span, div")
      ).filter(function(node) {
        return isVisible(node) && textOf(node) === targetOptionLabel;
      });

      var hasCheckedRadio = radioNodes.some(function(node) {
        var host =
          (node.matches && node.matches("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']") && node) ||
          (node.querySelector && node.querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
          (node.closest && node.closest("label") && node.closest("label").querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
          null;

        return !!host && !!host.checked;
      });

      var hasAriaChecked = radioNodes.some(function(node) {
        var host = node.closest && node.closest("[role='radio']");
        return !!host && host.getAttribute("aria-checked") === "true";
      });

      return hasCheckedRadio || hasAriaChecked;
    }

    function findPrioritizedRadio(targetRowLabel, targetOptionLabel, targetAnchorLabel) {
      var labelContainer = findRow(targetRowLabel, targetAnchorLabel, rowLabelOccurrence);
      var labelRect = labelContainer && labelContainer.getBoundingClientRect ? labelContainer.getBoundingClientRect() : { top: 0 };
      var labelTop = labelRect.top || 0;

      var candidates = Array.prototype.slice
        .call(labelContainer.querySelectorAll("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']"))
        .filter(function(node) {
          return isVisible(node);
        })
        .map(function(node) {
          var host =
            node.closest("label") ||
            node.parentElement ||
            node.closest("[role='radio']") ||
            node;
          var hostText = textOf(host);
          var container =
            node.closest("tr") ||
            node.closest(".item--wrapper") ||
            node.closest(".cr-section") ||
            node.closest("form") ||
            node.parentElement;
          var rect = host.getBoundingClientRect ? host.getBoundingClientRect() : { top: 0 };
          var score = 0;

          if (hostText === targetOptionLabel || normalizedIncludes(hostText, targetOptionLabel)) {
            score += 1000;
          }
          if (labelContainer && container === labelContainer) {
            score += 500;
          }
          score -= Math.abs((rect.top || 0) - labelTop);

          return {
            node: node,
            host: host,
            score: score,
          };
        })
        .sort(function(left, right) {
          return right.score - left.score;
        });

      return candidates.length ? candidates[0] : null;
    }

    var row = findRow(rowLabel, anchorLabel, rowLabelOccurrence);
    var triggerState = getRowTriggerState(rowLabel, "selectRadio", anchorLabel, rowLabelOccurrence);
    var option = Array.prototype.slice
      .call(row.querySelectorAll("label, span, div, button"))
      .find(function(node) {
        return isVisible(node) && textOf(node) === optionLabel;
      });

    if (!option) {
      throw new Error("Radio option not found for row " + rowLabel + ": " + optionLabel);
    }

    var prioritized = findPrioritizedRadio(rowLabel, optionLabel, anchorLabel);
    var clickTarget = (prioritized && prioritized.host) || option;
    var radioInput =
      (prioritized && prioritized.node) ||
      (option.matches && option.matches("input[type='radio']")
        ? option
        : option.querySelector && option.querySelector("input[type='radio']")
          ? option.querySelector("input[type='radio']")
          : option.closest && option.closest("label")
            ? option.closest("label").querySelector("input[type='radio']")
            : null);

    clickNode(clickTarget);

    if (!probeOnly && radioInput && !radioInput.checked) {
      clickNode(radioInput);
      radioInput.checked = true;
      radioInput.dispatchEvent(new Event("input", { bubbles: true }));
      radioInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await sleep(250);
    if (probeOnly) {
      try {
        await waitFor(function() {
          return radioSelectionSatisfied(rowLabel, optionLabel, anchorLabel);
        }, 800, 120);
      } catch (error) {}
    } else {
      await waitFor(function() {
        return radioSelectionSatisfied(rowLabel, optionLabel, anchorLabel);
      }, 4000, 120);
    }
    var checked = radioSelectionSatisfied(rowLabel, optionLabel, anchorLabel);

    var selectedState = {
      rowLabel: rowLabel,
      optionLabel: optionLabel,
      anchorLabel: anchorLabel || "",
      rowLabelOccurrence: rowLabelOccurrence || "",
      action: "selectRadio",
      checked: checked,
      ariaChecked: !!(clickTarget && clickTarget.closest && clickTarget.closest("[role='radio']") && clickTarget.closest("[role='radio']").getAttribute("aria-checked") === "true"),
      saveEnabled: isSaveEnabled(),
      probeOnly: probeOnly === true ? true : undefined,
      row_availability: triggerState.row_availability,
      row_disability: triggerState.row_disability,
      row_visibility: triggerState.row_visibility,
      rowText: textOf(findRow(rowLabel, anchorLabel, rowLabelOccurrence)),
    };

    return selectedState;
  }

  async function probeRadio(rowLabel, optionLabel, anchorLabel, rowLabelOccurrence) {
    var row = findRow(rowLabel, anchorLabel, rowLabelOccurrence);
    var nodes = Array.prototype.slice.call(
      row.querySelectorAll("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox'], [role='radio'], label, button, span, div")
    ).filter(function(node) {
      if (!isVisible(node)) return false;
      var host =
        (node.matches && node.matches("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']") && node.parentElement) ||
        (node.closest && node.closest("label")) ||
        node;
      var text = textOf(host);
      return text === optionLabel || normalizedIncludes(text, optionLabel);
    });

    var checked = nodes.some(function(node) {
      var input =
        (node.matches && node.matches("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']") && node) ||
        (node.querySelector && node.querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
        (node.closest && node.closest("label") && node.closest("label").querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
        null;
      var roleRadio = node.closest && node.closest("[role='radio']");
      return !!(input && input.checked) || !!(roleRadio && roleRadio.getAttribute("aria-checked") === "true");
    });

    return {
      rowLabel: rowLabel,
      optionLabel: optionLabel,
      anchorLabel: anchorLabel || "",
      rowLabelOccurrence: rowLabelOccurrence || "",
      action: "probeRadio",
      checked: checked,
      outcome: checked ? "passed" : "failed",
      rowText: textOf(row),
    };
  }

  async function selectComboboxOption(rowLabel, optionLabel) {
    var skip = rowSkipResult(rowLabel, "selectComboboxOption");
    if (skip) return skip;
    var row = findRow(rowLabel);
    var beforeRowText = textOf(row);
    var beforeRows = visibleRows();
    var triggers = comboboxTriggerCandidates(row);
    if (!triggers.length) {
      throw new Error("Combobox trigger not found for row: " + rowLabel);
    }
    var lastError = null;

    for (var index = 0; index < triggers.length; index += 1) {
      var trigger = triggers[index];
      try {
        if (trigger.tagName === "SELECT") {
          var nativeOption = Array.prototype.slice.call(trigger.options || []).find(function(option) {
            return normalize(option.text) === optionLabel || normalizedIncludes(option.text, optionLabel) || normalizedIncludes(optionLabel, option.text);
          });
          if (!nativeOption) {
            continue;
          }

          trigger.value = nativeOption.value;
          trigger.dispatchEvent(new Event("input", { bubbles: true }));
          trigger.dispatchEvent(new Event("change", { bubbles: true }));
          await waitForComboboxCommit(rowLabel, optionLabel, beforeRowText, beforeRows);
          return {
            rowLabel: rowLabel,
            optionLabel: optionLabel,
            value: textOf(findRow(rowLabel)),
            action: "selectComboboxOption",
          };
        }

        clickNode(trigger);
        await sleep(500);

        if (trigger.getAttribute("aria-expanded") === "false" || trigger.tagName === "INPUT") {
          trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
          trigger.dispatchEvent(new KeyboardEvent("keyup", { key: "ArrowDown", bubbles: true }));
          await sleep(250);
        }

        var option = await waitFor(function() {
          return findPopupOption(optionLabel);
        }, 1500, 100);

        clickNode(optionHost(option));
        await waitForComboboxCommit(rowLabel, optionLabel, beforeRowText, beforeRows);

        return {
          rowLabel: rowLabel,
          optionLabel: optionLabel,
          value: textOf(findRow(rowLabel)),
          action: "selectComboboxOption",
        };
      } catch (error) {
        lastError = error;
      }
    }

    var edgeTargets = rightEdgeClickTargets(row);
    for (var edgeIndex = 0; edgeIndex < edgeTargets.length; edgeIndex += 1) {
      var target = edgeTargets[edgeIndex];
      try {
        if (target.type === "node") {
          clickNode(target.node);
        } else {
          clickPoint(target.x, target.y);
        }
        await sleep(500);

        var optionFromEdge = await waitFor(function() {
          return findPopupOption(optionLabel);
        }, 1500, 100);

        clickNode(optionHost(optionFromEdge));
        await waitForComboboxCommit(rowLabel, optionLabel, beforeRowText, beforeRows);

        return {
          rowLabel: rowLabel,
          optionLabel: optionLabel,
          value: textOf(findRow(rowLabel)),
          action: "selectComboboxOption",
        };
      } catch (edgeError) {
        lastError = edgeError;
      }
    }

    throw lastError || new Error("Combobox option not found for row " + rowLabel + ": " + optionLabel);
  }

  async function clickButtonExactByLabel(buttonLabel) {
    var button = findButtonExact(buttonLabel);
    if (!button) {
      throw new Error("Button not found: " + buttonLabel);
    }

    if (button.disabled || button.getAttribute("aria-disabled") === "true") {
      throw new Error("Button is disabled: " + buttonLabel);
    }

    clickNode(button);
    await sleep(500);
    return {
      button: buttonLabel,
      action: "clickButtonExact",
    };
  }

  // Returns true when the 수정사유 (Reason for Change) popup is visible on screen.
  function hasReasonPopup() {
    return visibleTextNodes().some(function(node) {
      return textOf(node) === "수정사유";
    });
  }

  // Walk up from the 수정사유 label to find the popup's action button.
  // Depending on what triggered the popup the label is either "Save" or "Save & Next".
  function findPopupSaveButton() {
    var reasonNode = visibleTextNodes().find(function(node) {
      return textOf(node) === "수정사유";
    });
    if (!reasonNode) return null;

    var el = reasonNode;
    for (var i = 0; i < 20; i++) {
      el = el.parentElement;
      if (!el || el === document.body) break;
      var btns = Array.prototype.slice.call(el.querySelectorAll("button")).filter(function(b) {
        var t = textOf(b);
        return isVisible(b) && (t === "Save" || t === "Save & Next");
      });
      if (!btns.length) continue;
      // Prefer an enabled button; fall back to any matching button.
      return btns.find(function(b) {
        return !b.disabled && b.getAttribute("aria-disabled") !== "true";
      }) || btns[0];
    }
    return null;
  }

  async function clickSave() {
    // If the reason popup is already open, leave it to the service worker CDP
    // post-save handler. Fluent UI ignores page-context synthetic clicks.
    if (hasReasonPopup()) {
      return { action: "clickSave", button: "Save", reasonPopupOpen: true };
    }

    var button = findButtonExact("Save");
    if (!button) {
      throw new Error("Save button not found.");
    }

    if (button.disabled || button.getAttribute("aria-disabled") === "true") {
      throw new Error("Save button is disabled.");
    }

    clickNode(button);
    await sleep(500);

    // Clicking Save on an already-saved page triggers the reason popup — handle it.
    // The popup may take up to ~1.5 s to appear so wait with a short poll.
    if (!hasReasonPopup()) {
      try {
        await waitFor(hasReasonPopup, 1500, 100);
      } catch (e) { /* popup did not appear — normal save */ }
    }
    if (hasReasonPopup()) {
      return { action: "clickSave", button: "Save", reasonPopupOpen: true };
    }

    return { action: "clickSave", button: "Save" };
  }

  async function clickSaveNext() {
    // If the reason popup is already open, leave it to the service worker CDP
    // post-save handler. Fluent UI ignores page-context synthetic clicks.
    if (hasReasonPopup()) {
      return { action: "clickSaveNext", button: "Save & Next", reasonPopupOpen: true };
    }

    var pageBefore = global.location.pathname;
    var button = findButtonExact("Save & Next");
    if (!button) {
      throw new Error("Save & Next button not found.");
    }

    if (button.disabled || button.getAttribute("aria-disabled") === "true") {
      throw new Error("Save & Next button is disabled.");
    }

    var buttonLabel = textOf(button) || "Save & Next";
    clickNode(button);
    await sleep(500);

    // Clicking Save & Next on an already-saved page may trigger the reason popup.
    if (!hasReasonPopup()) {
      try { await waitFor(hasReasonPopup, 1500, 100); } catch (e) {}
    }
    if (hasReasonPopup()) {
      return {
        action: "clickSaveNext",
        button: "Save & Next",
        buttonLabel: buttonLabel,
        pageBefore: pageBefore,
        pageAfter: global.location.pathname,
        moved: false,
        reasonPopupOpen: true,
      };
    }

    try {
      await waitFor(function() {
        return global.location.pathname !== pageBefore;
      }, 5000, 150);
    } catch (error) {}

    return {
      action: "clickSaveNext",
      button: "Save & Next",
      buttonLabel: buttonLabel,
      pageBefore: pageBefore,
      pageAfter: global.location.pathname,
      moved: global.location.pathname !== pageBefore,
    };
  }

  async function navigateToUrl(url) {
    if (!url) {
      throw new Error("navigateToUrl requires a url.");
    }
    var beforePath = global.location.pathname;
    global.location.href = url;
    // SPA (React Router) navigation: frame is not removed, so wait for the URL
    // to actually change before returning so evaluateOutcome sees before != after.
    // Full-page reloads remove the frame before this resolves — that's fine.
    try {
      await waitFor(function() {
        return global.location.pathname !== beforePath;
      }, 3000, 100);
    } catch (e) {}
    return { action: "navigateToUrl", url: url };
  }

  async function chooseModifyReason(reasonLabel) {
    var label = reasonLabel || "Input Error";

    // Find the radio/checkbox input whose label text matches.
    // CDMS may use either standard <input type="radio"> or Fluent UI
    // .cr-clearable-radio-buttons input[type="checkbox"] inside the popup.
    var radioInput = null;
    var clickTarget = null;
    var norm = normalize(label);
    Array.prototype.slice.call(document.querySelectorAll(
      "input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']"
    ))
      .filter(isVisible)
      .forEach(function(ri) {
        if (radioInput) return;
        var host = ri.closest("label") || ri.parentElement || ri;
        var hostText = normalize(textOf(host));
        if (hostText === norm || hostText.indexOf(norm) >= 0) {
          radioInput = ri;
          clickTarget = host;
        }
      });

    // Fallback: plain visible text node
    if (!clickTarget) {
      clickTarget = visibleTextNodes().find(function(node) {
        return normalize(textOf(node)) === norm || normalize(textOf(node)).indexOf(norm) >= 0;
      });
    }

    if (!clickTarget) {
      return {
        action: "chooseModifyReason",
        handled: false,
        reasonLabel: label,
      };
    }

    // Attempt to click the host element (isTrusted=false — Fluent UI will ignore this).
    // CDP-based selection is handled by service-worker postSavePopupHandler.
    clickNode(clickTarget);
    await sleep(200);

    // Wait for the popup's own Save button to become enabled after selecting a reason.
    var popupSave;
    try {
      popupSave = await waitFor(function() { return findPopupSaveButton(); }, 2000, 100);
    } catch (e) {
      throw new Error("Reason popup Save button not found after selecting: " + label);
    }

    var popupBtnLabel = textOf(popupSave);
    var beforePath = global.location.pathname;
    clickNode(popupSave);
    await sleep(300);

    if (popupBtnLabel === "Save & Next") {
      // Wait for the page to actually navigate before returning so that
      // evaluateOutcome sees a changed pathname and marks the step "passed".
      try {
        await waitFor(function() {
          return global.location.pathname !== beforePath;
        }, 4000, 200);
      } catch (e) {
        // Navigation didn't happen within 8 s — let evaluateOutcome decide.
      }
    } else {
      await sleep(300); // Save-only: just wait for the save to complete.
    }

    return {
      action: "chooseModifyReason",
      handled: true,
      reasonLabel: label,
    };
  }

  async function assertPath(pathContains, timeout) {
    var expected = pathContains;
    await waitFor(function() {
      return global.location.pathname.indexOf(expected) >= 0;
    }, timeout || 10000, 150);

    return {
      action: "assertPath",
      pathContains: expected,
      pathname: global.location.pathname,
    };
  }

  function evaluateOutcome(testCase, before, after, signals, error) {
    if (error) {
      return {
        outcome: "failed",
        failureReason: error.message || String(error),
      };
    }

    var navigation = testCase && testCase.expected ? testCase.expected.navigation : null;
    var uiExpectation = testCase && testCase.expected ? testCase.expected.ui : null;
    var queryExpectation = testCase && testCase.expected ? testCase.expected.query : null;
    var validationExpectation = testCase && testCase.expected ? testCase.expected.validation : null;

    if (uiExpectation) {
      var revealConfigured = !!(uiExpectation.shouldReveal && uiExpectation.shouldReveal.length);
      var enableConfigured = !!(uiExpectation.shouldEnableActions && uiExpectation.shouldEnableActions.length);
      var revealed = !revealConfigured || uiExpectation.shouldReveal.every(function(label) {
        return after.visibleRows.indexOf(label) >= 0;
      });
      var enabled = !enableConfigured || uiExpectation.shouldEnableActions.every(function(label) {
        return after.enabledActions.indexOf(label) >= 0;
      });

      if ((revealConfigured && revealed) || (enableConfigured && enabled) || (!revealConfigured && !enableConfigured)) {
        return { outcome: "passed" };
      }

      return {
        outcome: "failed",
        failureReason: "Expected UI state change was not detected after the action.",
      };
    }

    if (navigation && navigation.shouldMove === true) {
      if (navigation.nextPathContains && after.pathname.indexOf(navigation.nextPathContains) >= 0) {
        return { outcome: "passed" };
      }
      // No specific path required — just verify the URL actually changed
      if (!navigation.nextPathContains && before.pathname !== after.pathname) {
        return { outcome: "passed" };
      }
      return {
        outcome: "failed",
        failureReason: "Expected navigation to " + (navigation.nextPathContains || "new page") + " but stayed on " + after.pathname,
      };
    }

    if (navigation && navigation.shouldMove === false) {
      var stayed = before.pathname === after.pathname || (navigation.currentPathContains && after.pathname.indexOf(navigation.currentPathContains) >= 0);
      if (stayed) {
        return {
          outcome: validationExpectation && validationExpectation.shouldBlockNavigation ? "blocked" : "passed",
        };
      }

      return {
        outcome: "failed",
        failureReason: "Navigation was expected to be blocked but path changed to " + after.pathname,
      };
    }

    if (queryExpectation && queryExpectation.messageIncludes && queryExpectation.messageIncludes.length) {
      var haystack = [document.body.innerText || "", signals.toastTexts.join(" "), signals.modalTexts.join(" ")].join("\n");
      var matched = queryExpectation.messageIncludes.some(function(text) {
        return haystack.indexOf(text) >= 0;
      });

      return matched
        ? { outcome: "passed" }
        : {
            outcome: "failed",
            failureReason: "Expected query text was not detected on the page.",
          };
    }

    // No expectations defined — action ran without error, treat as passed.
    return { outcome: "passed" };
  }

  async function runStep(step) {
    if (!step || !step.action) {
      return null;
    }

    switch (step.action) {
      case "setText":
        return setText(step.rowLabel, step.value);
      case "setDateViaCalendarPopup":
        return setDateViaCalendarPopup(step.rowLabel, step.value);
      case "selectComboboxOption":
        return selectComboboxOption(step.rowLabel, step.optionLabel);
      case "selectRadio":
        return selectRadio(step.rowLabel, step.optionLabel, step.anchorLabel, step.probeOnly, step.rowLabelOccurrence);
      case "probeRadio":
        return probeRadio(step.rowLabel, step.optionLabel, step.anchorLabel, step.rowLabelOccurrence);
      case "clickButtonExact":
        return clickButtonExactByLabel(step.buttonLabel);
      case "goBack": {
        var beforeGoBackPath = global.location.pathname;
        global.history.back();
        await sleep(300);
        try {
          await waitFor(function() {
            return global.location.pathname !== beforeGoBackPath;
          }, 4000, 200);
        } catch (e) { /* let evaluateOutcome decide */ }
        return { action: "goBack" };
      }
      case "navigateToUrl":
        return navigateToUrl(step.url);
      case "clickSave":
        return clickSave();
      case "clickSaveNext":
        return clickSaveNext();
      case "chooseModifyReason":
        return chooseModifyReason(step.reasonLabel);
      case "clickQueryAction":
        return clickQueryAction(step.queryLabel, step.queryAction || "cancel");
      case "assertPath":
        return assertPath(step.pathContains);
      case "capturePage":
        return capturePage();
      case "noop":
        return { action: "noop", note: step.note || "" };
      default:
        throw new Error("Unsupported action: " + step.action);
    }
  }

  async function runCase(testCase) {
    installNetworkWatcher();

    var startedAt = nowIso();
    var before = inspectActivePage();
    var inputs = [];
    var clickedButtons = [];
    var modals = [];
    var error = null;

    try {
      for (var index = 0; index < (testCase.steps || []).length; index += 1) {
        var step = testCase.steps[index];
        var result = await runStep(step);
        if (!result) {
          continue;
        }

        if (result.rowLabel || step.rowLabel) {
          inputs.push({
            action: step.action,
            rowLabel: result.rowLabel || step.rowLabel,
            value: result.value || step.value,
            optionLabel: result.optionLabel || step.optionLabel,
            outcome: result.outcome,
            skipped: result.skipped === true ? true : undefined,
            reason: result.reason || undefined,
            row_visibility: result.row_visibility || undefined,
            row_availability: result.row_availability || undefined,
            row_disability: result.row_disability || undefined,
            checked: typeof result.checked === "boolean" ? result.checked : undefined,
            ariaChecked: typeof result.ariaChecked === "boolean" ? result.ariaChecked : undefined,
            saveEnabled: typeof result.saveEnabled === "boolean" ? result.saveEnabled : undefined,
            rowText: result.rowText || undefined,
          });
        }

        if (result.button) {
          clickedButtons.push(result.button);
        }

        if (result.handled) {
          modals.push(result.reasonLabel || step.reasonLabel || "modal");
        }
      }
    } catch (stepError) {
      error = stepError;
    }

    var after = inspectActivePage();
    var signals = collectValidationSignals();
    var evaluation = evaluateOutcome(testCase, before, after, signals, error);

    return {
      runId: "run-" + Date.now(),
      caseId: testCase.id,
      studyId: testCase.studyId,
      runner: "tm",
      pageBefore: before.pathname,
      pageAfter: after.pathname,
      inputs: inputs,
      clickedButtons: clickedButtons,
      modals: modals,
      networkEvents: networkEvents.slice(-50),
      domSignals: {
        currentUrl: after.url,
        currentPath: after.pathname,
        invalidCount: signals.invalidCount,
        invalidRowLabels: signals.invalidRowLabels,
        toastTexts: signals.toastTexts,
        modalTexts: signals.modalTexts,
        buttonStates: signals.buttonStates,
      },
      outcome: evaluation.outcome,
      failureReason: evaluation.failureReason,
      artifacts: {
        before: before,
        after: after,
      },
      startedAt: startedAt,
      finishedAt: nowIso(),
    };
  }

  function toggleDebugOverlay() {
    if (debugOverlay) {
      debugOverlay.remove();
      debugOverlay = null;
      return false;
    }

    debugOverlay = document.createElement("div");
    debugOverlay.id = "__cdm-agent-debug-overlay";
    debugOverlay.style.position = "fixed";
    debugOverlay.style.right = "12px";
    debugOverlay.style.bottom = "12px";
    debugOverlay.style.zIndex = "2147483647";
    debugOverlay.style.width = "360px";
    debugOverlay.style.maxHeight = "50vh";
    debugOverlay.style.overflow = "auto";
    debugOverlay.style.padding = "12px";
    debugOverlay.style.borderRadius = "8px";
    debugOverlay.style.boxShadow = "0 12px 24px rgba(0,0,0,0.18)";
    debugOverlay.style.background = "rgba(17, 24, 39, 0.92)";
    debugOverlay.style.color = "#f9fafb";
    debugOverlay.style.font = "12px/1.4 monospace";
    var snapshot = inspectActivePage();
    var summary = {
      page: snapshot.pageLabel,
      queryCount: snapshot.queryCount,
      rawPageLabel: snapshot.rawPageLabel,
      pageStatus: snapshot.pageStatus,
      queryRows: snapshot.queryRows,
    };
    debugOverlay.textContent = JSON.stringify(summary, null, 2) + "\n\n" + JSON.stringify(snapshot, null, 2);
    document.body.appendChild(debugOverlay);

    return true;
  }

  installNetworkWatcher();

  // Returns viewport-relative center coords of the <label for="input.id"> for a radio option.
  // Used by service-worker CDP click so the browser generates a trusted mouse event.
  function getRadioLabelCoords(rowLabel, optionLabel, anchorLabel, rowLabelOccurrence) {
    var norm = normalize(optionLabel);
    var row = findRow(rowLabel, anchorLabel, rowLabelOccurrence);
    // CDMS uses input[type='checkbox'] inside .cr-clearable-radio-buttons as radio buttons
    var radios = Array.prototype.slice.call(row.querySelectorAll(
      "input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']"
    )).filter(function(r) { return r.isConnected; });
    for (var i = 0; i < radios.length; i++) {
      var r = radios[i];
      var assocLabel = r.id ? document.querySelector("label[for='" + r.id + "']") : null;
      var host = assocLabel || r.closest("label") || r.parentElement || r;
      var t = normalize(textOf(host));
      if (t === norm || t.indexOf(norm) >= 0) {
        var target = assocLabel || host;
        target.scrollIntoView({ block: "center", inline: "nearest" });
        var rect = target.getBoundingClientRect();
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      }
    }
    return null;
  }

  function isRadioOptionSelected(rowLabel, optionLabel, anchorLabel, rowLabelOccurrence) {
    var norm = normalize(optionLabel);
    var row = findRow(rowLabel, anchorLabel, rowLabelOccurrence);
    var candidates = Array.prototype.slice.call(row.querySelectorAll(
      "input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox'], [role='radio'], label, button, span"
    )).filter(function(node) {
      if (!isVisible(node)) return false;
      var host = node.closest && node.closest("label") || node;
      var text = normalize(textOf(host));
      return text === norm || text.indexOf(norm) >= 0;
    });

    return candidates.some(function(node) {
      var input =
        (node.matches && node.matches("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']") && node) ||
        (node.querySelector && node.querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
        (node.closest && node.closest("label") && node.closest("label").querySelector("input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']")) ||
        null;
      var roleRadio = node.closest && node.closest("[role='radio']");
      return !!(input && input.checked) || !!(roleRadio && roleRadio.getAttribute("aria-checked") === "true");
    });
  }

  // Returns viewport-relative center coords of the modify-reason radio label.
  // Used by service-worker CDP click so the browser generates isTrusted=true events.
  function getModifyReasonLabelCoords(reasonLabel) {
    if (!hasReasonPopup()) return null;
    var norm = normalize(reasonLabel);
    var radios = Array.prototype.slice.call(document.querySelectorAll(
      "input[type='radio'], .cr-clearable-radio-buttons input[type='checkbox']"
    )).filter(function(r) { return r.isConnected && isVisible(r); });
    for (var i = 0; i < radios.length; i++) {
      var r = radios[i];
      var host = r.closest("label") || r.parentElement || r;
      var t = normalize(textOf(host));
      if (t === norm || t.indexOf(norm) >= 0) {
        host.scrollIntoView({ block: "center", inline: "nearest" });
        var rect = host.getBoundingClientRect();
        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      }
    }
    // Fallback: find visible text node
    var node = visibleTextNodes().find(function(n) {
      return normalize(textOf(n)) === norm;
    });
    if (node) {
      node.scrollIntoView({ block: "center", inline: "nearest" });
      var rect = node.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    }
    return null;
  }

  // Returns viewport-relative center coords of the popup's Save/Save & Next button.
  function getPopupSaveButtonCoords() {
    var btn = findPopupSaveButton();
    if (!btn) return null;
    btn.scrollIntoView({ block: "center", inline: "nearest" });
    var rect = btn.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  function getDateInputCoords(rowLabel) {
    var row = findRow(rowLabel);
    var target = row.querySelector("i[data-icon-name='Calendar']")
      || row.querySelector(".GrDatePicker button")
      || Array.prototype.slice.call(row.querySelectorAll("button, [role='button'], [tabindex='0']")).find(function(el) {
        var label = (el.getAttribute("aria-label") || "").toLowerCase();
        var hasSvg = el.querySelector("svg") !== null;
        return label.includes("date") || label.includes("달력") || label.includes("calendar") || hasSvg;
      })
      || Array.prototype.slice.call(row.querySelectorAll("input")).find(function(node) {
        return isVisible(node) && node.type !== "hidden";
      });
    if (!target) return null;
    target.scrollIntoView({ block: "center", inline: "nearest" });
    var rect = target.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  global.__CDMAgentRunner = {
    version: RUNNER_VERSION,
    sleep: sleep,
    waitFor: waitFor,
    findRow: findRow,
    setText: setText,
    setDateViaCalendarPopup: setDateViaCalendarPopup,
    selectRadio: selectRadio,
    probeRadio: probeRadio,
    selectComboboxOption: selectComboboxOption,
    clickSave: clickSave,
    clickSaveNext: clickSaveNext,
    clickButtonExactByLabel: clickButtonExactByLabel,
    navigateToUrl: navigateToUrl,
    chooseModifyReason: chooseModifyReason,
    assertPath: assertPath,
    collectValidationSignals: collectValidationSignals,
    capturePage: capturePage,
    listNavPages: listNavPages,
    inspectActivePage: inspectActivePage,
    waitForQueryMessages: waitForQueryMessages,
    runCase: runCase,
    getRadioLabelCoords: getRadioLabelCoords,
    isRadioOptionSelected: isRadioOptionSelected,
    getDateInputCoords: getDateInputCoords,
    getQueryActionCoords: getQueryActionCoords,
    clickQueryAction: clickQueryAction,
    getModifyReasonLabelCoords: getModifyReasonLabelCoords,
    getPopupSaveButtonCoords: getPopupSaveButtonCoords,
    toggleDebugOverlay: toggleDebugOverlay,
    getNetworkEvents: function() {
      return networkEvents.slice();
    },
  };
  installQueryObserver();
})(window);
