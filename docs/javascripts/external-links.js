document$.subscribe(function () {
  document.querySelectorAll("a[href]").forEach(function (link) {
    if (!/^https?:$/.test(link.protocol)) return
    if (!link.hostname || link.hostname === window.location.hostname) return
    link.target = "_blank"
    link.rel = "noopener noreferrer"
  })
})
