(function bootstrapCDMAgentRunner(global) {
  if (global.__CDMAgentRunner) {
    return;
  }

  var networkEvents = [];
  var networkWatcherInstalled = false;
  var debugOverlay = null;

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
    return String(text || "")
      .replace(/\s+/g, " ")
      .trim();
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

  function findRow(rowLabel) {
    var allMatches = visibleTextNodes().filter(function(node) {
      return textOf(node) === rowLabel;
    });

    // Priority 1: not nav AND not inside app-study-crf-group-header (section title)
    var labelNode = allMatches.find(function(node) {
      if (isNavNode(node)) return false;
      var tr = node.closest("tr");
      return !tr || !tr.classList.contains("app-study-crf-group-header");
    })
    // Priority 2: not nav (may be group header)
    || allMatches.find(function(node) { return !isNavNode(node); })
    || allMatches[0];

    if (!labelNode) {
      throw new Error("Row label not found: " + rowLabel);
    }

    var row = (
      labelNode.closest("tr") ||
      labelNode.parentElement.closest("tr") ||
      labelNode.closest(".item--wrapper") ||
      labelNode.closest(".cr-section") ||
      labelNode.parentElement
    );

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

  function findEditableInput(root) {
    return Array.prototype.slice
      .call(root.querySelectorAll("input, textarea"))
      .find(function(node) {
        return isVisible(node) && !node.disabled && !node.readOnly && node.type !== "hidden" && node.tabIndex !== -1;
      });
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

  function activePageLabel() {
    var activeSidebar = Array.prototype.slice
      .call(document.querySelectorAll("[aria-current='page'], .active, .selected, .is-active"))
      .find(function(node) {
        return isVisible(node) && textOf(node);
      });

    if (activeSidebar) {
      return textOf(activeSidebar);
    }

    var heading = Array.prototype.slice.call(document.querySelectorAll("h1, h2, h3")).find(function(node) {
      return isVisible(node) && textOf(node);
    });

    return heading ? textOf(heading) : "";
  }

  function inspectActivePage() {
    var signals = collectValidationSignals();
    return {
      url: global.location.href,
      pathname: global.location.pathname,
      pageLabel: activePageLabel(),
      visibleRows: visibleRows(),
      enabledActions: signals.buttonStates.filter(function(button) {
        return !button.disabled;
      }).map(function(button) {
        return button.label;
      }),
      invalidRowLabels: signals.invalidRowLabels,
      invalidCount: signals.invalidCount,
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

  async function setText(rowLabel, value) {
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
      await sleep(100);
      var preEnter = findButtonExact("Enter");
      if (preEnter) { clickNode(preEnter); await sleep(400); }
      return { rowLabel: rowLabel, value: value, action: "setDateViaCalendarPopup" };
    }

    var row = findRow(rowLabel);

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
      try { fallbackInput.readOnly = false; } catch (e) {}
      clickNode(fallbackInput);
      setNativeValue(fallbackInput, value || "");
      fallbackInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      fallbackInput.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
      fallbackInput.dispatchEvent(new Event("blur", { bubbles: true }));
      await sleep(400);
    }

    var mainInput = Array.prototype.slice.call(row.querySelectorAll("input")).find(function(node) {
      return isVisible(node);
    });

    return {
      rowLabel: rowLabel,
      value: mainInput ? mainInput.value : value,
      action: "setDateViaCalendarPopup",
    };
  }

  async function selectRadio(rowLabel, optionLabel) {
    function pageContainsValidationQuery(targetRowLabel) {
      var pageText = normalize(document.body && document.body.innerText ? document.body.innerText : "");
      return pageText.indexOf("[" + targetRowLabel + "] ?낅젰 ?꾨씫") >= 0;
    }

    function radioSelectionSatisfied(targetRowLabel, targetOptionLabel) {
      var queryCleared = !pageContainsValidationQuery(targetRowLabel);
      var row = null;
      try {
        row = findRow(targetRowLabel);
      } catch (error) {}

      var radioNodes = Array.prototype.slice.call(
        document.querySelectorAll("input[type='radio'], [role='radio'], label, button, span, div")
      ).filter(function(node) {
        return isVisible(node) && textOf(node) === targetOptionLabel;
      });

      var hasCheckedRadio = radioNodes.some(function(node) {
        var host =
          (node.matches && node.matches("input[type='radio']") && node) ||
          (node.querySelector && node.querySelector("input[type='radio']")) ||
          (node.closest && node.closest("label") && node.closest("label").querySelector("input[type='radio']")) ||
          null;

        return !!host && !!host.checked;
      });

      var hasAriaChecked = radioNodes.some(function(node) {
        var host = node.closest && node.closest("[role='radio']");
        return !!host && host.getAttribute("aria-checked") === "true";
      });

      if (row) {
        var rowText = textOf(row);
        if (normalizedIncludes(rowText, targetOptionLabel) && (queryCleared || isSaveEnabled())) {
          return true;
        }
      }

      return hasCheckedRadio || hasAriaChecked || queryCleared || isSaveEnabled();
    }

    function findPrioritizedRadio(targetRowLabel, targetOptionLabel) {
      var labelNode = findVisibleTextNodeExact(targetRowLabel);
      var labelContainer = labelNode
        ? (labelNode.closest("tr") ||
          labelNode.closest(".item--wrapper") ||
          labelNode.closest(".cr-section") ||
          labelNode.closest("form") ||
          labelNode.parentElement)
        : null;
      var labelTop = labelNode && labelNode.getBoundingClientRect ? labelNode.getBoundingClientRect().top : 0;

      var candidates = Array.prototype.slice
        .call(document.querySelectorAll("input[type='radio']"))
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

    var row = findRow(rowLabel);
    var option = Array.prototype.slice
      .call(row.querySelectorAll("label, span, div, button"))
      .find(function(node) {
        return isVisible(node) && textOf(node) === optionLabel;
      });

    if (!option) {
      var labelNode = findVisibleTextNodeExact(rowLabel);
      var optionCandidates = visibleTextNodes().filter(function(node) {
        return textOf(node) === optionLabel;
      });

      if (labelNode && optionCandidates.length) {
        var labelSection = labelNode.closest(".cr-section, .section, form, table") || document.body;
        var labelTop = labelNode.getBoundingClientRect ? labelNode.getBoundingClientRect().top : 0;

        option = optionCandidates
          .map(function(node) {
            var host = node.closest("label, button, [role='radio'], div, span") || node;
            var sameSection = (host.closest(".cr-section, .section, form, table") || document.body) === labelSection;
            var rect = host.getBoundingClientRect ? host.getBoundingClientRect() : { top: 0 };
            return {
              host: host,
              score: (sameSection ? 1000 : 0) - Math.abs((rect.top || 0) - labelTop),
            };
          })
          .sort(function(left, right) {
            return right.score - left.score;
          })[0];

        option = option ? option.host : null;
      }
    }

    if (!option) {
      throw new Error("Radio option not found for row " + rowLabel + ": " + optionLabel);
    }

    var prioritized = findPrioritizedRadio(rowLabel, optionLabel);
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

    if (radioInput && !radioInput.checked) {
      clickNode(radioInput);
      radioInput.checked = true;
      radioInput.dispatchEvent(new Event("input", { bubbles: true }));
      radioInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await sleep(250);
    await waitFor(function() {
      return radioSelectionSatisfied(rowLabel, optionLabel);
    }, 4000, 120);

    var selectedState = {
      rowLabel: rowLabel,
      optionLabel: optionLabel,
      action: "selectRadio",
      checked: !!(radioInput && radioInput.checked),
      ariaChecked: !!(clickTarget && clickTarget.closest && clickTarget.closest("[role='radio']") && clickTarget.closest("[role='radio']").getAttribute("aria-checked") === "true"),
      saveEnabled: isSaveEnabled(),
      rowText: textOf(findRow(rowLabel)),
    };

    return selectedState;
  }

  async function selectComboboxOption(rowLabel, optionLabel) {
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

  async function clickSave() {
    var button = findButtonExact("Save");
    if (!button) {
      throw new Error("Save button not found.");
    }

    if (button.disabled || button.getAttribute("aria-disabled") === "true") {
      throw new Error("Save button is disabled.");
    }

    clickNode(button);
    await sleep(500);
    return { action: "clickSave", button: "Save" };
  }

  async function clickSaveNext() {
    var button = findButtonExact("Save & Next");
    if (!button) {
      throw new Error("Save & Next button not found.");
    }

    if (button.disabled || button.getAttribute("aria-disabled") === "true") {
      throw new Error("Save & Next button is disabled.");
    }

    clickNode(button);
    await sleep(500);
    return { action: "clickSaveNext", button: "Save & Next" };
  }

  async function navigateToUrl(url) {
    if (!url) {
      throw new Error("navigateToUrl requires a url.");
    }

    global.location.href = url;
    await sleep(1200);
    return {
      action: "navigateToUrl",
      url: global.location.href,
    };
  }

  async function chooseModifyReason(reasonLabel) {
    var label = reasonLabel || "Input Error";
    var option = visibleTextNodes().find(function(node) {
      return textOf(node) === label;
    });

    if (!option) {
      return {
        action: "chooseModifyReason",
        handled: false,
        reasonLabel: label,
      };
    }

    clickNode(option);
    await sleep(150);

    var modalSaveNext = Array.prototype.slice
      .call(document.querySelectorAll("button"))
      .filter(isVisible)
      .find(function(button) {
        return textOf(button) === "Save & Next" && !button.disabled;
      });

    if (!modalSaveNext) {
      throw new Error("Modify reason Save & Next button not found.");
    }

    clickNode(modalSaveNext);
    await sleep(500);

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
        return selectRadio(step.rowLabel, step.optionLabel);
      case "clickButtonExact":
        return clickButtonExactByLabel(step.buttonLabel);
      case "navigateToUrl":
        return navigateToUrl(step.url);
      case "clickSave":
        return clickSave();
      case "clickSaveNext":
        return clickSaveNext();
      case "chooseModifyReason":
        return chooseModifyReason(step.reasonLabel);
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
    debugOverlay.textContent = JSON.stringify(inspectActivePage(), null, 2);
    document.body.appendChild(debugOverlay);

    return true;
  }

  installNetworkWatcher();

  global.__CDMAgentRunner = {
    sleep: sleep,
    waitFor: waitFor,
    findRow: findRow,
    setText: setText,
    setDateViaCalendarPopup: setDateViaCalendarPopup,
    selectRadio: selectRadio,
    selectComboboxOption: selectComboboxOption,
    clickSave: clickSave,
    clickSaveNext: clickSaveNext,
    clickButtonExactByLabel: clickButtonExactByLabel,
    navigateToUrl: navigateToUrl,
    chooseModifyReason: chooseModifyReason,
    assertPath: assertPath,
    collectValidationSignals: collectValidationSignals,
    capturePage: capturePage,
    inspectActivePage: inspectActivePage,
    runCase: runCase,
    toggleDebugOverlay: toggleDebugOverlay,
    getNetworkEvents: function() {
      return networkEvents.slice();
    },
  };
})(window);

