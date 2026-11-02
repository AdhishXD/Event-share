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

document.querySelectorAll("[data-event-photo-upload]").forEach((form) => {
  const input = form.querySelector("[data-event-photo-input]");
  const summary = form.querySelector("[data-event-photo-summary]");
  const list = form.querySelector("[data-event-photo-list]");
  const feedback = form.querySelector("[data-event-photo-feedback]");
  const submit = form.querySelector('button[type="submit"]');
  let selected = [];
  let uploading = false;
  input.required = false;

  const fileKey = (file) => [file.name, file.size, file.lastModified, file.type].join("\u0000");

  const render = () => {
    summary.textContent = `${selected.length} photo${selected.length === 1 ? "" : "s"} selected`;
    list.replaceChildren();

    selected.forEach((file) => {
      const item = document.createElement("li");
      const filename = document.createElement("span");
      const remove = document.createElement("button");
      filename.textContent = file.name;
      remove.type = "button";
      remove.className = "text-danger";
      remove.disabled = uploading;
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        selected = selected.filter((selectedFile) => selectedFile !== file);
        render();
      });
      item.append(filename, remove);
      list.append(item);
    });
  };

  input.addEventListener("change", () => {
    const existing = new Set(selected.map(fileKey));
    let duplicates = 0;
    Array.from(input.files || []).forEach((file) => {
      const key = fileKey(file);
      if (existing.has(key)) {
        duplicates += 1;
      } else {
        existing.add(key);
        selected.push(file);
      }
    });
    input.value = "";
    render();
    feedback.textContent = duplicates
      ? `${duplicates} already selected photo${duplicates === 1 ? " was" : "s were"} skipped.`
      : "";
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (uploading) return;
    if (!selected.length) {
      feedback.textContent = "Choose at least one photo before uploading.";
      feedback.classList.add("error");
      input.focus();
      return;
    }
    const formData = new FormData(form);
    formData.delete(input.name);
    selected.forEach((file) => formData.append(input.name, file, file.name));
    uploading = true;
    input.disabled = true;
    submit.disabled = true;
    form.setAttribute("aria-busy", "true");
    feedback.textContent = "";
    feedback.classList.remove("error", "success");

    try {
      const response = await fetch(form.action, {
        method: form.method,
        body: formData,
        credentials: "same-origin",
      });
      const responseHtml = await response.text();
      const result = new DOMParser().parseFromString(responseHtml, "text/html");
      const message = result.querySelector(".flash");
      if (!response.ok || !message) {
        feedback.textContent = message?.textContent.trim() || "Upload failed. Your selected photos are still available; try again.";
        feedback.classList.add("error");
        return;
      }
      if (!message.classList.contains("success")) {
        feedback.textContent = message.textContent.trim();
        feedback.classList.add("error");
        return;
      }

      selected = [];
      render();
      feedback.textContent = message.textContent.trim();
      feedback.classList.add("success");
    } catch {
      feedback.textContent = "Upload failed. Your selected photos are still available; try again.";
      feedback.classList.add("error");
    } finally {
      uploading = false;
      input.disabled = false;
      submit.disabled = false;
      list.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      form.removeAttribute("aria-busy");
    }
  });
});

document.querySelectorAll('input[type="file"]:not([data-reference-library]):not([data-reference-camera]):not([data-event-photo-input])').forEach((input) => {
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
  const list = picker.querySelector("[data-reference-list]");
  const feedback = picker.querySelector("[data-reference-feedback]");
  const openCamera = picker.querySelector("[data-open-camera]");
  const dialog = picker.querySelector("[data-camera-dialog]");
  const video = picker.querySelector("[data-camera-video]");
  const canvas = picker.querySelector("[data-camera-canvas]");
  const capture = picker.querySelector("[data-capture-photo]");
  const cameraStatus = picker.querySelector("[data-camera-status]");
  const form = picker.closest("form");
  const submit = form.querySelector('button[type="submit"]');
  let selected = [];
  let stream = null;
  let uploading = false;
  library.required = false;

  const update = (files) => {
    const existing = new Set(selected.map((file) => [file.name, file.size, file.lastModified, file.type].join("\u0000")));
    let duplicates = 0;
    let excess = 0;
    Array.from(files).forEach((file) => {
      const key = [file.name, file.size, file.lastModified, file.type].join("\u0000");
      if (existing.has(key)) {
        duplicates += 1;
      } else if (selected.length >= 5) {
        excess += 1;
      } else {
        existing.add(key);
        selected.push(file);
      }
    });
    library.value = "";
    const count = selected.length;
    summary.textContent = count
      ? `${count} of 5 reference photo${count === 1 ? "" : "s"} selected${count < 2 ? " · add at least one more" : ""}`
      : "No photos selected · 2–5 required";
    picker.classList.toggle("has-files", count > 0);
    list.replaceChildren();
    selected.forEach((file) => {
      const item = document.createElement("li");
      const filename = document.createElement("span");
      const remove = document.createElement("button");
      filename.textContent = file.name;
      remove.type = "button";
      remove.className = "text-danger";
      remove.disabled = uploading;
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        selected = selected.filter((selectedFile) => selectedFile !== file);
        update([]);
      });
      item.append(filename, remove);
      list.append(item);
    });
    feedback.textContent = excess
      ? "You can select up to 5 reference photos. Additional photos were not added."
      : duplicates
        ? `${duplicates} already selected photo${duplicates === 1 ? " was" : "s were"} skipped.`
        : "";
    feedback.classList.remove("success");
    feedback.classList.toggle("error", excess > 0);
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (uploading) return;
    if (selected.length < 2 || selected.length > 5) {
      feedback.textContent = "Choose between 2 and 5 reference photos before creating your profile.";
      feedback.classList.add("error");
      library.focus();
      return;
    }

    const formData = new FormData(form);
    formData.delete(library.name);
    selected.forEach((file) => formData.append(library.name, file, file.name));
    uploading = true;
    library.disabled = true;
    camera.disabled = true;
    openCamera.disabled = true;
    capture.disabled = true;
    submit.disabled = true;
    picker.setAttribute("aria-busy", "true");
    list.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    feedback.textContent = "";
    feedback.classList.remove("error", "success");
    closeCamera();

    try {
      const response = await fetch(form.action, {
        method: form.method,
        body: formData,
        credentials: "same-origin",
      });
      const responseHtml = await response.text();
      const result = new DOMParser().parseFromString(responseHtml, "text/html");
      const message = result.querySelector(".flash");
      if (!response.ok || !message) {
        feedback.textContent = message?.textContent.trim() || "Enrollment failed. Your selected photos are still available; try again.";
        feedback.classList.add("error");
        return;
      }
      if (!message.classList.contains("success")) {
        feedback.textContent = message.textContent.trim();
        feedback.classList.add("error");
        return;
      }

      selected = [];
      update([]);
      feedback.textContent = message.textContent.trim();
      feedback.classList.add("success");
    } catch {
      feedback.textContent = "Enrollment failed. Your selected photos are still available; try again.";
      feedback.classList.add("error");
    } finally {
      uploading = false;
      library.disabled = false;
      camera.disabled = false;
      openCamera.disabled = false;
      submit.disabled = false;
      list.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      picker.removeAttribute("aria-busy");
    }
  });

  library.addEventListener("change", () => update(library.files));
  camera.addEventListener("change", () => {
    if (!camera.files?.length) return;
    update(camera.files);
    camera.value = "";
  });

  const stopCamera = () => {
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    capture.disabled = true;
  };

  const closeCamera = () => {
    if (dialog.open) dialog.close();
    stopCamera();
  };

  openCamera.addEventListener("click", async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof dialog.showModal !== "function") {
      camera.click();
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
        audio: false,
      });
      video.srcObject = stream;
      cameraStatus.textContent = "Look directly at the camera, then vary your angle slightly for each photo.";
      dialog.showModal();
    } catch {
      feedback.textContent = "Camera access was unavailable. Allow camera permission or choose photos instead.";
      feedback.classList.add("error");
    }
  });

  video.addEventListener("loadedmetadata", () => {
    capture.disabled = false;
  });

  capture.addEventListener("click", () => {
    if (!video.videoWidth || selected.length >= 5) {
      cameraStatus.textContent = selected.length >= 5 ? "You already have the maximum of 5 photos." : "The camera is still starting. Try again in a moment.";
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    context.translate(canvas.width, 0);
    context.scale(-1, 1);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const photo = new File([blob], `camera-reference-${Date.now()}.jpg`, { type: "image/jpeg" });
      update([...selected, photo]);
      cameraStatus.textContent = `Photo added · ${selected.length} of 5 selected${selected.length < 2 ? " · take at least one more" : ""}`;
    }, "image/jpeg", 0.9);
  });

  picker.querySelector("[data-close-camera]").addEventListener("click", closeCamera);
  picker.querySelector("[data-done-camera]").addEventListener("click", closeCamera);
  dialog.addEventListener("close", stopCamera);
  dialog.addEventListener("cancel", stopCamera);
});
