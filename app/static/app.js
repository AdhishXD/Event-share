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
  const openCamera = picker.querySelector("[data-open-camera]");
  const dialog = picker.querySelector("[data-camera-dialog]");
  const video = picker.querySelector("[data-camera-video]");
  const canvas = picker.querySelector("[data-camera-canvas]");
  const capture = picker.querySelector("[data-capture-photo]");
  const cameraStatus = picker.querySelector("[data-camera-status]");
  let selected = [];
  let stream = null;

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
      summary.textContent = "Camera access was unavailable. Allow camera permission or choose photos instead.";
      picker.classList.remove("has-files");
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
