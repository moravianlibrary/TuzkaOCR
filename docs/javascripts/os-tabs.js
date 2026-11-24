document$.subscribe(function () {
  try {
    for (var i = 0; i < localStorage.length; i++) {
      if (/__tabs$/.test(localStorage.key(i))) return
    }
  } catch (e) {
    return
  }
  var platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent
  var system = /Win/i.test(platform) ? "Windows" : /Mac/i.test(platform) ? "Mac" : /Linux|X11/i.test(platform) ? "Linux" : null
  if (!system) return
  document.querySelectorAll(".tabbed-set").forEach(function (set) {
    var labels = Array.prototype.slice.call(set.querySelectorAll(":scope > .tabbed-labels > label"))
    var inputs = Array.prototype.slice.call(set.querySelectorAll(":scope > input"))
    var index = labels.findIndex(function (el) { return el.textContent.trim() === system })
    if (index >= 0 && inputs[index]) inputs[index].checked = true
  })
})
