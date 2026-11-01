document.documentElement.classList.add("js");

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const label = button.querySelector("span");
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      if (label) label.textContent = "Copied";
      button.classList.add("copied");
    } catch {
      if (label) label.textContent = button.dataset.copy;
    }
  });
});

document.querySelectorAll('input[type="file"]:not([data-reference-library]):not([data-reference-camera])').forEach((input) => {
  input.addEventListener("change", () => {
    const label = input.closest("label");
    const caption = label?.querySelector("span");
    if (!caption || !input.files?.length) return;
    caption.textContent = input.files.length === 1 ? input.files[0].name : `${input.files.length} photos selected`;
    label.classList.add("has-files");
  });
});

document.querySelectorAll("[data-reference-picker]").forEach((picker) => {
  const library = picker.querySelector("[data-reference-library]");
  const camera = picker.querySelector("[data-reference-camera]");
  const summary = picker.querySelector("[data-reference-summary]");
  let selected = [];

  const update = (files) => {
    selected = Array.from(files).slice(0, 5);
    const transfer = new DataTransfer();
    selected.forEach((file) => transfer.items.add(file));
    library.files = transfer.files;
    const count = selected.length;
    summary.textContent = count
      ? `${count} of 5 reference photo${count === 1 ? "" : "s"} selected${count < 2 ? " · add at least one more" : ""}`
      : "No photos selected · 2–5 required";
    picker.classList.toggle("has-files", count > 0);
  };

  library.addEventListener("change", () => update(library.files));
  camera.addEventListener("change", () => {
    if (!camera.files?.length) return;
    update([...selected, ...camera.files]);
    camera.value = "";
  });
});
