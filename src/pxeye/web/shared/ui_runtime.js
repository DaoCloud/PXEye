"use strict";

// Explicit ownership of page rendering, actions and delegated UI observers.
const pageRenderers = new Map();
const actionHandlers = new Map();
const uiObservers = new Map();
const pagePollers = new Map();
const lifecycleHooks = new Map();

function registerPage(name, renderer) {
  if (pageRenderers.has(name)) throw Error(`Duplicate page: ${name}`);
  pageRenderers.set(name, renderer);
}

function registerActions(owner, actions, callback) {
  for (const action of actions) {
    if (actionHandlers.has(action)) throw Error(`Duplicate action: ${action}`);
    actionHandlers.set(action, { owner, callback });
  }
}

function observeUI(event, owner, callback, capture = false) {
  const key = `${event}:${capture}`;
  if (!uiObservers.has(key)) {
    uiObservers.set(key, []);
    document.addEventListener(
      event,
      (value) => {
        for (const observer of uiObservers.get(key)) {
          try {
            Promise.resolve(observer.callback(value)).catch((error) =>
              toast(error.message),
            );
          } catch (error) {
            toast(error.message);
          }
        }
      },
      capture,
    );
  }
  uiObservers.get(key).push({ owner, callback });
}

function registerHook(name, callback) {
  if (!lifecycleHooks.has(name)) lifecycleHooks.set(name, []);
  lifecycleHooks.get(name).push(callback);
}

function runHooks(name, ...args) {
  for (const callback of lifecycleHooks.get(name) || []) callback(...args);
}

function registerPoller(name, pages, callback, interval = 5000) {
  if (pagePollers.has(name)) throw Error(`Duplicate poller: ${name}`);
  pagePollers.set(name, { pages, callback, interval, timer: null });
}

function syncPollers(page) {
  for (const poller of pagePollers.values()) {
    const active = poller.pages.includes(page) || poller.pages.includes("*");
    if (!active && poller.timer) {
      clearInterval(poller.timer);
      poller.timer = null;
    } else if (active && !poller.timer) {
      poller.timer = setInterval(poller.callback, poller.interval);
    }
  }
}

document.addEventListener("click", async (event) => {
  const element = event.target.closest("[data-live]");
  if (!element || element.disabled) return;
  const handler = actionHandlers.get(element.dataset.live);
  if (handler) {
    try {
      await handler.callback(event);
    } catch (error) {
      toast(error.message);
    }
  }
});
