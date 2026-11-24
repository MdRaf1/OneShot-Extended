(function () {
  "use strict";

  const tabButtons = document.querySelectorAll(".tab-button");
  const tabPanels = document.querySelectorAll(".tab-panel");

  function showTab(name) {
    tabPanels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === "tab-" + name);
    });
    tabButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
  }

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => showTab(button.dataset.tab));
  });
  showTab("scan");

  let lastScanResults = [];

  function refreshQueue() {
    fetch("/api/queue/targets")
      .then((response) => response.json())
      .then((data) => {
        const list = document.getElementById("queue-results");
        list.innerHTML = "";
        data.targets.forEach((target) => {
          const li = document.createElement("li");
          let text = target.label + ": " + target.status_text;
          if (target.progress_percent !== null && target.progress_percent !== undefined) {
            text += " (" + target.progress_percent + "%)";
          }
          li.textContent = text;
          list.appendChild(li);
        });
      });
  }

  document.getElementById("scan-button").addEventListener("click", () => {
    fetch("/api/scan")
      .then((response) => response.json())
      .then((networks) => {
        lastScanResults = networks;
        const list = document.getElementById("scan-results");
        list.innerHTML = "";
        networks.forEach((network, index) => {
          const li = document.createElement("li");
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.dataset.index = String(index);
          const label = document.createElement("label");
          label.textContent = network.label;
          li.appendChild(checkbox);
          li.appendChild(label);
          list.appendChild(li);
        });
      });
  });

  document.getElementById("enqueue-button").addEventListener("click", () => {
    const checkboxes = document.querySelectorAll("#scan-results input[type=checkbox]:checked");
    checkboxes.forEach((checkbox) => {
      const network = lastScanResults[Number(checkbox.dataset.index)];
      fetch("/api/queue/targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bssid: network.bssid, essid: network.essid }),
      });
    });
  });

  document.getElementById("start-button").addEventListener("click", () => {
    fetch("/api/queue/start", { method: "POST" }).then(refreshQueue);
  });

  document.getElementById("stop-button").addEventListener("click", () => {
    fetch("/api/queue/stop", { method: "POST" }).then(refreshQueue);
  });

  document.getElementById("pbc-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const bssid = document.getElementById("pbc-bssid").value.trim() || null;
    const statusEl = document.getElementById("pbc-status");
    fetch("/api/pbc/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bssid: bssid }),
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        statusEl.textContent = ok ? "Started" : data.detail;
      });
  });

  const logOutput = document.getElementById("log-output");
  const eventSource = new EventSource("/api/events");
  eventSource.onmessage = (event) => {
    logOutput.textContent += event.data + "\n";
    logOutput.scrollTop = logOutput.scrollHeight;
    refreshQueue();
  };

  refreshQueue();
})();
