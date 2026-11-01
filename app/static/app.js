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

document.querySelectorAll('input[type="file"]').forEach((input) => {
  input.addEventListener("change", () => {
    const label = input.closest("label");
    const caption = label?.querySelector("span");
    if (!caption || !input.files?.length) return;
    caption.textContent = input.files.length === 1 ? input.files[0].name : `${input.files.length} photos selected`;
    label.classList.add("has-files");
  });
});
