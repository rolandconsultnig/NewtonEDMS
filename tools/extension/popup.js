const $ = (id) => document.getElementById(id);

async function save() {
  await chrome.storage.local.set({ base: $("base").value, token: $("token").value });
}

document.addEventListener("DOMContentLoaded", async () => {
  const st = await chrome.storage.local.get(["base", "token"]);
  $("base").value = st.base || "http://127.0.0.1:8000";
  $("token").value = st.token || "";
  $("base").onchange = save;
  $("token").onchange = save;
  $("search").onclick = async () => {
    await save();
    const r = await fetch(`${$("base").value}/api/query?q=${encodeURIComponent($("q").value)}`, { credentials: "include" });
    $("out").textContent = await r.text();
  };
  $("up").onclick = async () => {
    await save();
    const f = $("file").files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch(`${$("base").value}/api/v1/open/upload/item/${$("token").value}`, { method: "POST", body: fd });
    $("out").textContent = await r.text();
  };
});
