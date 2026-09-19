(() => {
  var __defProp = Object.defineProperty;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  // node_modules/fancy-canvas/size.mjs
  function size(_a) {
    var width = _a.width, height = _a.height;
    if (width < 0) {
      throw new Error("Negative width is not allowed for Size");
    }
    if (height < 0) {
      throw new Error("Negative height is not allowed for Size");
    }
    return {
      width,
      height
    };
  }
  function equalSizes(first, second2) {
    return first.width === second2.width && first.height === second2.height;
  }

  // node_modules/fancy-canvas/device-pixel-ratio.mjs
  var Observable = (
    /** @class */
    (function() {
      function Observable2(win) {
        var _this = this;
        this._resolutionListener = function() {
          return _this._onResolutionChanged();
        };
        this._resolutionMediaQueryList = null;
        this._observers = [];
        this._window = win;
        this._installResolutionListener();
      }
      Observable2.prototype.dispose = function() {
        this._uninstallResolutionListener();
        this._window = null;
      };
      Object.defineProperty(Observable2.prototype, "value", {
        get: function() {
          return this._window.devicePixelRatio;
        },
        enumerable: false,
        configurable: true
      });
      Observable2.prototype.subscribe = function(next) {
        var _this = this;
        var observer = { next };
        this._observers.push(observer);
        return {
          unsubscribe: function() {
            _this._observers = _this._observers.filter(function(o2) {
              return o2 !== observer;
            });
          }
        };
      };
      Observable2.prototype._installResolutionListener = function() {
        if (this._resolutionMediaQueryList !== null) {
          throw new Error("Resolution listener is already installed");
        }
        var dppx = this._window.devicePixelRatio;
        this._resolutionMediaQueryList = this._window.matchMedia("all and (resolution: ".concat(dppx, "dppx)"));
        this._resolutionMediaQueryList.addListener(this._resolutionListener);
      };
      Observable2.prototype._uninstallResolutionListener = function() {
        if (this._resolutionMediaQueryList !== null) {
          this._resolutionMediaQueryList.removeListener(this._resolutionListener);
          this._resolutionMediaQueryList = null;
        }
      };
      Observable2.prototype._reinstallResolutionListener = function() {
        this._uninstallResolutionListener();
        this._installResolutionListener();
      };
      Observable2.prototype._onResolutionChanged = function() {
        var _this = this;
        this._observers.forEach(function(observer) {
          return observer.next(_this._window.devicePixelRatio);
        });
        this._reinstallResolutionListener();
      };
      return Observable2;
    })()
  );
  function createObservable(win) {
    return new Observable(win);
  }

  // node_modules/fancy-canvas/canvas-element-bitmap-size.mjs
  var DevicePixelContentBoxBinding = (
    /** @class */
    (function() {
      function DevicePixelContentBoxBinding2(canvasElement, transformBitmapSize, options) {
        var _a;
        this._canvasElement = null;
        this._bitmapSizeChangedListeners = [];
        this._suggestedBitmapSize = null;
        this._suggestedBitmapSizeChangedListeners = [];
        this._devicePixelRatioObservable = null;
        this._canvasElementResizeObserver = null;
        this._canvasElement = canvasElement;
        this._canvasElementClientSize = size({
          width: this._canvasElement.clientWidth,
          height: this._canvasElement.clientHeight
        });
        this._transformBitmapSize = transformBitmapSize !== null && transformBitmapSize !== void 0 ? transformBitmapSize : (function(size2) {
          return size2;
        });
        this._allowResizeObserver = (_a = options === null || options === void 0 ? void 0 : options.allowResizeObserver) !== null && _a !== void 0 ? _a : true;
        this._chooseAndInitObserver();
      }
      DevicePixelContentBoxBinding2.prototype.dispose = function() {
        var _a, _b;
        if (this._canvasElement === null) {
          throw new Error("Object is disposed");
        }
        (_a = this._canvasElementResizeObserver) === null || _a === void 0 ? void 0 : _a.disconnect();
        this._canvasElementResizeObserver = null;
        (_b = this._devicePixelRatioObservable) === null || _b === void 0 ? void 0 : _b.dispose();
        this._devicePixelRatioObservable = null;
        this._suggestedBitmapSizeChangedListeners.length = 0;
        this._bitmapSizeChangedListeners.length = 0;
        this._canvasElement = null;
      };
      Object.defineProperty(DevicePixelContentBoxBinding2.prototype, "canvasElement", {
        get: function() {
          if (this._canvasElement === null) {
            throw new Error("Object is disposed");
          }
          return this._canvasElement;
        },
        enumerable: false,
        configurable: true
      });
      Object.defineProperty(DevicePixelContentBoxBinding2.prototype, "canvasElementClientSize", {
        get: function() {
          return this._canvasElementClientSize;
        },
        enumerable: false,
        configurable: true
      });
      Object.defineProperty(DevicePixelContentBoxBinding2.prototype, "bitmapSize", {
        get: function() {
          return size({
            width: this.canvasElement.width,
            height: this.canvasElement.height
          });
        },
        enumerable: false,
        configurable: true
      });
      DevicePixelContentBoxBinding2.prototype.resizeCanvasElement = function(clientSize) {
        this._canvasElementClientSize = size(clientSize);
        this.canvasElement.style.width = "".concat(this._canvasElementClientSize.width, "px");
        this.canvasElement.style.height = "".concat(this._canvasElementClientSize.height, "px");
        this._invalidateBitmapSize();
      };
      DevicePixelContentBoxBinding2.prototype.subscribeBitmapSizeChanged = function(listener) {
        this._bitmapSizeChangedListeners.push(listener);
      };
      DevicePixelContentBoxBinding2.prototype.unsubscribeBitmapSizeChanged = function(listener) {
        this._bitmapSizeChangedListeners = this._bitmapSizeChangedListeners.filter(function(l2) {
          return l2 !== listener;
        });
      };
      Object.defineProperty(DevicePixelContentBoxBinding2.prototype, "suggestedBitmapSize", {
        get: function() {
          return this._suggestedBitmapSize;
        },
        enumerable: false,
        configurable: true
      });
      DevicePixelContentBoxBinding2.prototype.subscribeSuggestedBitmapSizeChanged = function(listener) {
        this._suggestedBitmapSizeChangedListeners.push(listener);
      };
      DevicePixelContentBoxBinding2.prototype.unsubscribeSuggestedBitmapSizeChanged = function(listener) {
        this._suggestedBitmapSizeChangedListeners = this._suggestedBitmapSizeChangedListeners.filter(function(l2) {
          return l2 !== listener;
        });
      };
      DevicePixelContentBoxBinding2.prototype.applySuggestedBitmapSize = function() {
        if (this._suggestedBitmapSize === null) {
          return;
        }
        var oldSuggestedSize = this._suggestedBitmapSize;
        this._suggestedBitmapSize = null;
        this._resizeBitmap(oldSuggestedSize);
        this._emitSuggestedBitmapSizeChanged(oldSuggestedSize, this._suggestedBitmapSize);
      };
      DevicePixelContentBoxBinding2.prototype._resizeBitmap = function(newSize) {
        var oldSize = this.bitmapSize;
        if (equalSizes(oldSize, newSize)) {
          return;
        }
        this.canvasElement.width = newSize.width;
        this.canvasElement.height = newSize.height;
        this._emitBitmapSizeChanged(oldSize, newSize);
      };
      DevicePixelContentBoxBinding2.prototype._emitBitmapSizeChanged = function(oldSize, newSize) {
        var _this = this;
        this._bitmapSizeChangedListeners.forEach(function(listener) {
          return listener.call(_this, oldSize, newSize);
        });
      };
      DevicePixelContentBoxBinding2.prototype._suggestNewBitmapSize = function(newSize) {
        var oldSuggestedSize = this._suggestedBitmapSize;
        var finalNewSize = size(this._transformBitmapSize(newSize, this._canvasElementClientSize));
        var newSuggestedSize = equalSizes(this.bitmapSize, finalNewSize) ? null : finalNewSize;
        if (oldSuggestedSize === null && newSuggestedSize === null) {
          return;
        }
        if (oldSuggestedSize !== null && newSuggestedSize !== null && equalSizes(oldSuggestedSize, newSuggestedSize)) {
          return;
        }
        this._suggestedBitmapSize = newSuggestedSize;
        this._emitSuggestedBitmapSizeChanged(oldSuggestedSize, newSuggestedSize);
      };
      DevicePixelContentBoxBinding2.prototype._emitSuggestedBitmapSizeChanged = function(oldSize, newSize) {
        var _this = this;
        this._suggestedBitmapSizeChangedListeners.forEach(function(listener) {
          return listener.call(_this, oldSize, newSize);
        });
      };
      DevicePixelContentBoxBinding2.prototype._chooseAndInitObserver = function() {
        var _this = this;
        if (!this._allowResizeObserver) {
          this._initDevicePixelRatioObservable();
          return;
        }
        isDevicePixelContentBoxSupported().then(function(isSupported) {
          return isSupported ? _this._initResizeObserver() : _this._initDevicePixelRatioObservable();
        });
      };
      DevicePixelContentBoxBinding2.prototype._initDevicePixelRatioObservable = function() {
        var _this = this;
        if (this._canvasElement === null) {
          return;
        }
        var win = canvasElementWindow(this._canvasElement);
        if (win === null) {
          throw new Error("No window is associated with the canvas");
        }
        this._devicePixelRatioObservable = createObservable(win);
        this._devicePixelRatioObservable.subscribe(function() {
          return _this._invalidateBitmapSize();
        });
        this._invalidateBitmapSize();
      };
      DevicePixelContentBoxBinding2.prototype._invalidateBitmapSize = function() {
        var _a, _b;
        if (this._canvasElement === null) {
          return;
        }
        var win = canvasElementWindow(this._canvasElement);
        if (win === null) {
          return;
        }
        var ratio = (_b = (_a = this._devicePixelRatioObservable) === null || _a === void 0 ? void 0 : _a.value) !== null && _b !== void 0 ? _b : win.devicePixelRatio;
        var canvasRects = this._canvasElement.getClientRects();
        var newSize = (
          // eslint-disable-next-line no-negated-condition
          canvasRects[0] !== void 0 ? predictedBitmapSize(canvasRects[0], ratio) : size({
            width: this._canvasElementClientSize.width * ratio,
            height: this._canvasElementClientSize.height * ratio
          })
        );
        this._suggestNewBitmapSize(newSize);
      };
      DevicePixelContentBoxBinding2.prototype._initResizeObserver = function() {
        var _this = this;
        if (this._canvasElement === null) {
          return;
        }
        this._canvasElementResizeObserver = new ResizeObserver(function(entries) {
          var entry = entries.find(function(entry2) {
            return entry2.target === _this._canvasElement;
          });
          if (!entry || !entry.devicePixelContentBoxSize || !entry.devicePixelContentBoxSize[0]) {
            return;
          }
          var entrySize = entry.devicePixelContentBoxSize[0];
          var newSize = size({
            width: entrySize.inlineSize,
            height: entrySize.blockSize
          });
          _this._suggestNewBitmapSize(newSize);
        });
        this._canvasElementResizeObserver.observe(this._canvasElement, { box: "device-pixel-content-box" });
      };
      return DevicePixelContentBoxBinding2;
    })()
  );
  function bindTo(canvasElement, target) {
    if (target.type === "device-pixel-content-box") {
      return new DevicePixelContentBoxBinding(canvasElement, target.transform, target.options);
    }
    throw new Error("Unsupported binding target");
  }
  function canvasElementWindow(canvasElement) {
    return canvasElement.ownerDocument.defaultView;
  }
  function isDevicePixelContentBoxSupported() {
    return new Promise(function(resolve) {
      var ro = new ResizeObserver(function(entries) {
        resolve(entries.every(function(entry) {
          return "devicePixelContentBoxSize" in entry;
        }));
        ro.disconnect();
      });
      ro.observe(document.body, { box: "device-pixel-content-box" });
    }).catch(function() {
      return false;
    });
  }
  function predictedBitmapSize(canvasRect, ratio) {
    return size({
      width: Math.round(canvasRect.left * ratio + canvasRect.width * ratio) - Math.round(canvasRect.left * ratio),
      height: Math.round(canvasRect.top * ratio + canvasRect.height * ratio) - Math.round(canvasRect.top * ratio)
    });
  }

  // node_modules/fancy-canvas/canvas-rendering-target.mjs
  var CanvasRenderingTarget2D = (
    /** @class */
    (function() {
      function CanvasRenderingTarget2D2(context, mediaSize, bitmapSize) {
        if (mediaSize.width === 0 || mediaSize.height === 0) {
          throw new TypeError("Rendering target could only be created on a media with positive width and height");
        }
        this._mediaSize = mediaSize;
        if (bitmapSize.width === 0 || bitmapSize.height === 0) {
          throw new TypeError("Rendering target could only be created using a bitmap with positive integer width and height");
        }
        this._bitmapSize = bitmapSize;
        this._context = context;
      }
      CanvasRenderingTarget2D2.prototype.useMediaCoordinateSpace = function(f2) {
        try {
          this._context.save();
          this._context.setTransform(1, 0, 0, 1, 0, 0);
          this._context.scale(this._horizontalPixelRatio, this._verticalPixelRatio);
          return f2({
            context: this._context,
            mediaSize: this._mediaSize
          });
        } finally {
          this._context.restore();
        }
      };
      CanvasRenderingTarget2D2.prototype.useBitmapCoordinateSpace = function(f2) {
        try {
          this._context.save();
          this._context.setTransform(1, 0, 0, 1, 0, 0);
          return f2({
            context: this._context,
            mediaSize: this._mediaSize,
            bitmapSize: this._bitmapSize,
            horizontalPixelRatio: this._horizontalPixelRatio,
            verticalPixelRatio: this._verticalPixelRatio
          });
        } finally {
          this._context.restore();
        }
      };
      Object.defineProperty(CanvasRenderingTarget2D2.prototype, "_horizontalPixelRatio", {
        get: function() {
          return this._bitmapSize.width / this._mediaSize.width;
        },
        enumerable: false,
        configurable: true
      });
      Object.defineProperty(CanvasRenderingTarget2D2.prototype, "_verticalPixelRatio", {
        get: function() {
          return this._bitmapSize.height / this._mediaSize.height;
        },
        enumerable: false,
        configurable: true
      });
      return CanvasRenderingTarget2D2;
    })()
  );
  function tryCreateCanvasRenderingTarget2D(binding, contextOptions) {
    var mediaSize = binding.canvasElementClientSize;
    if (mediaSize.width === 0 || mediaSize.height === 0) {
      return null;
    }
    var bitmapSize = binding.bitmapSize;
    if (bitmapSize.width === 0 || bitmapSize.height === 0) {
      return null;
    }
    var context = binding.canvasElement.getContext("2d", contextOptions);
    if (context === null) {
      return null;
    }
    return new CanvasRenderingTarget2D(context, mediaSize, bitmapSize);
  }

  // node_modules/lightweight-charts/dist/lightweight-charts.production.mjs
  var e = { title: "", visible: true, lastValueVisible: true, priceLineVisible: true, priceLineSource: 0, priceLineWidth: 1, priceLineColor: "", priceLineStyle: 2, baseLineVisible: true, baseLineWidth: 1, baseLineColor: "#B2B5BE", baseLineStyle: 0, priceFormat: { type: "price", precision: 2, minMove: 0.01 } };
  var r;
  var h;
  function a(t, i) {
    const s = { 0: [], 1: [t.lineWidth, t.lineWidth], 2: [2 * t.lineWidth, 2 * t.lineWidth], 3: [6 * t.lineWidth, 6 * t.lineWidth], 4: [t.lineWidth, 4 * t.lineWidth] }[i];
    t.setLineDash(s);
  }
  function l(t, i, s, n) {
    t.beginPath();
    const e3 = t.lineWidth % 2 ? 0.5 : 0;
    t.moveTo(s, i + e3), t.lineTo(n, i + e3), t.stroke();
  }
  function o(t, i) {
    if (!t) throw new Error("Assertion failed" + (i ? ": " + i : ""));
  }
  function _(t) {
    if (void 0 === t) throw new Error("Value is undefined");
    return t;
  }
  function u(t) {
    if (null === t) throw new Error("Value is null");
    return t;
  }
  function c(t) {
    return u(_(t));
  }
  !(function(t) {
    t[t.Simple = 0] = "Simple", t[t.WithSteps = 1] = "WithSteps", t[t.Curved = 2] = "Curved";
  })(r || (r = {})), (function(t) {
    t[t.Solid = 0] = "Solid", t[t.Dotted = 1] = "Dotted", t[t.Dashed = 2] = "Dashed", t[t.LargeDashed = 3] = "LargeDashed", t[t.SparseDotted = 4] = "SparseDotted";
  })(h || (h = {}));
  var d = class {
    constructor() {
      this.t = [];
    }
    i(t, i, s) {
      const n = { h: t, l: i, o: true === s };
      this.t.push(n);
    }
    _(t) {
      const i = this.t.findIndex(((i2) => t === i2.h));
      i > -1 && this.t.splice(i, 1);
    }
    u(t) {
      this.t = this.t.filter(((i) => i.l !== t));
    }
    p(t, i, s) {
      const n = [...this.t];
      this.t = this.t.filter(((t2) => !t2.o)), n.forEach(((n2) => n2.h(t, i, s)));
    }
    v() {
      return this.t.length > 0;
    }
    m() {
      this.t = [];
    }
  };
  function f(t, ...i) {
    for (const s of i) for (const i2 in s) void 0 !== s[i2] && Object.prototype.hasOwnProperty.call(s, i2) && !["__proto__", "constructor", "prototype"].includes(i2) && ("object" != typeof s[i2] || void 0 === t[i2] || Array.isArray(s[i2]) ? t[i2] = s[i2] : f(t[i2], s[i2]));
    return t;
  }
  function p(t) {
    return "number" == typeof t && isFinite(t);
  }
  function v(t) {
    return "number" == typeof t && t % 1 == 0;
  }
  function m(t) {
    return "string" == typeof t;
  }
  function w(t) {
    return "boolean" == typeof t;
  }
  function g(t) {
    const i = t;
    if (!i || "object" != typeof i) return i;
    let s, n, e3;
    for (n in s = Array.isArray(i) ? [] : {}, i) i.hasOwnProperty(n) && (e3 = i[n], s[n] = e3 && "object" == typeof e3 ? g(e3) : e3);
    return s;
  }
  function M(t) {
    return null !== t;
  }
  function b(t) {
    return null === t ? void 0 : t;
  }
  var S = "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif";
  function x(t, i, s) {
    return void 0 === i && (i = S), `${s = void 0 !== s ? `${s} ` : ""}${t}px ${i}`;
  }
  var C = class {
    constructor(t) {
      this.M = { S: 1, C: 5, P: NaN, k: "", T: "", R: "", D: "", V: 0, B: 0, I: 0, A: 0, L: 0 }, this.O = t;
    }
    N() {
      const t = this.M, i = this.F(), s = this.W();
      return t.P === i && t.T === s || (t.P = i, t.T = s, t.k = x(i, s), t.A = 2.5 / 12 * i, t.V = t.A, t.B = i / 12 * t.C, t.I = i / 12 * t.C, t.L = 0), t.R = this.H(), t.D = this.U(), this.M;
    }
    H() {
      return this.O.N().layout.textColor;
    }
    U() {
      return this.O.$();
    }
    F() {
      return this.O.N().layout.fontSize;
    }
    W() {
      return this.O.N().layout.fontFamily;
    }
  };
  function P(t) {
    return t < 0 ? 0 : t > 255 ? 255 : Math.round(t) || 0;
  }
  function y(t) {
    return 0.199 * t[0] + 0.687 * t[1] + 0.114 * t[2];
  }
  var k = class {
    constructor(t, i) {
      this.q = /* @__PURE__ */ new Map(), this.Y = t, i && (this.q = i);
    }
    j(t, i) {
      if ("transparent" === t) return t;
      const s = this.K(t), n = s[3];
      return `rgba(${s[0]}, ${s[1]}, ${s[2]}, ${i * n})`;
    }
    X(t) {
      const i = this.K(t);
      return { Z: `rgb(${i[0]}, ${i[1]}, ${i[2]})`, G: y(i) > 160 ? "black" : "white" };
    }
    J(t) {
      return y(this.K(t));
    }
    tt(t, i, s) {
      const [n, e3, r2, h2] = this.K(t), [a2, l2, o2, _2] = this.K(i), u2 = [P(n + s * (a2 - n)), P(e3 + s * (l2 - e3)), P(r2 + s * (o2 - r2)), (c2 = h2 + s * (_2 - h2), c2 <= 0 || c2 > 1 ? Math.min(Math.max(c2, 0), 1) : Math.round(1e4 * c2) / 1e4)];
      var c2;
      return `rgba(${u2[0]}, ${u2[1]}, ${u2[2]}, ${u2[3]})`;
    }
    K(t) {
      const i = this.q.get(t);
      if (i) return i;
      const s = (function(t2) {
        const i2 = document.createElement("div");
        i2.style.display = "none", document.body.appendChild(i2), i2.style.color = t2;
        const s2 = window.getComputedStyle(i2).color;
        return document.body.removeChild(i2), s2;
      })(t), n = s.match(/^rgba?\s*\((\d+),\s*(\d+),\s*(\d+)(?:,\s*(\d*\.?\d+))?\)$/);
      if (!n) {
        if (this.Y.length) for (const i2 of this.Y) {
          const s2 = i2(t);
          if (s2) return this.q.set(t, s2), s2;
        }
        throw new Error(`Failed to parse color: ${t}`);
      }
      const e3 = [parseInt(n[1], 10), parseInt(n[2], 10), parseInt(n[3], 10), n[4] ? parseFloat(n[4]) : 1];
      return this.q.set(t, e3), e3;
    }
  };
  var T = class {
    constructor() {
      this.it = [];
    }
    st(t) {
      this.it = t;
    }
    nt(t, i, s) {
      this.it.forEach(((n) => {
        n.nt(t, i, s);
      }));
    }
  };
  var R = class {
    nt(t, i, s) {
      t.useBitmapCoordinateSpace(((t2) => this.et(t2, i, s)));
    }
  };
  var D = class extends R {
    constructor() {
      super(...arguments), this.rt = null;
    }
    ht(t) {
      this.rt = t;
    }
    et({ context: t, horizontalPixelRatio: i, verticalPixelRatio: s }) {
      if (null === this.rt || null === this.rt.lt) return;
      const n = this.rt.lt, e3 = this.rt, r2 = Math.max(1, Math.floor(i)) % 2 / 2, h2 = (h3) => {
        t.beginPath();
        for (let a2 = n.to - 1; a2 >= n.from; --a2) {
          const n2 = e3.ot[a2], l2 = Math.round(n2._t * i) + r2, o2 = n2.ut * s, _2 = h3 * s + r2;
          t.moveTo(l2, o2), t.arc(l2, o2, _2, 0, 2 * Math.PI);
        }
        t.fill();
      };
      e3.ct > 0 && (t.fillStyle = e3.dt, h2(e3.ft + e3.ct)), t.fillStyle = e3.vt, h2(e3.ft);
    }
  };
  function V() {
    return { ot: [{ _t: 0, ut: 0, wt: 0, gt: 0 }], vt: "", dt: "", ft: 0, ct: 0, lt: null };
  }
  var B = { from: 0, to: 1 };
  var I = class {
    constructor(t, i, s) {
      this.Mt = new T(), this.bt = [], this.St = [], this.xt = true, this.O = t, this.Ct = i, this.Pt = s, this.Mt.st(this.bt);
    }
    yt(t) {
      this.kt(), this.xt = true;
    }
    Tt() {
      return this.xt && (this.Rt(), this.xt = false), this.Mt;
    }
    kt() {
      const t = this.Pt.Dt();
      t.length !== this.bt.length && (this.St = t.map(V), this.bt = this.St.map(((t2) => {
        const i = new D();
        return i.ht(t2), i;
      })), this.Mt.st(this.bt));
    }
    Rt() {
      const t = 2 === this.Ct.N().mode || !this.Ct.Vt(), i = this.Pt.Bt(), s = this.Ct.It(), n = this.O.Et();
      this.kt(), i.forEach(((i2, e3) => {
        const r2 = this.St[e3], h2 = i2.At(s), a2 = i2.zt();
        !t && null !== h2 && i2.Vt() && null !== a2 ? (r2.vt = h2.Lt, r2.ft = h2.ft, r2.ct = h2.Ot, r2.ot[0].gt = h2.gt, r2.ot[0].ut = i2.Ft().Nt(h2.gt, a2.Wt), r2.dt = h2.Ht ?? this.O.Ut(r2.ot[0].ut / i2.Ft().$t()), r2.ot[0].wt = s, r2.ot[0]._t = n.qt(s), r2.lt = B) : r2.lt = null;
      }));
    }
  };
  var E = class extends R {
    constructor(t) {
      super(), this.Yt = t;
    }
    et({ context: t, bitmapSize: i, horizontalPixelRatio: s, verticalPixelRatio: n }) {
      if (null === this.Yt) return;
      const e3 = this.Yt.jt.Vt, r2 = this.Yt.Kt.Vt;
      if (!e3 && !r2) return;
      const h2 = Math.round(this.Yt._t * s), o2 = Math.round(this.Yt.ut * n);
      t.lineCap = "butt", e3 && h2 >= 0 && (t.lineWidth = Math.floor(this.Yt.jt.ct * s), t.strokeStyle = this.Yt.jt.R, t.fillStyle = this.Yt.jt.R, a(t, this.Yt.jt.Xt), (function(t2, i2, s2, n2) {
        t2.beginPath();
        const e4 = t2.lineWidth % 2 ? 0.5 : 0;
        t2.moveTo(i2 + e4, s2), t2.lineTo(i2 + e4, n2), t2.stroke();
      })(t, h2, 0, i.height)), r2 && o2 >= 0 && (t.lineWidth = Math.floor(this.Yt.Kt.ct * n), t.strokeStyle = this.Yt.Kt.R, t.fillStyle = this.Yt.Kt.R, a(t, this.Yt.Kt.Xt), l(t, o2, 0, i.width));
    }
  };
  var A = class {
    constructor(t, i) {
      this.xt = true, this.Zt = { jt: { ct: 1, Xt: 0, R: "", Vt: false }, Kt: { ct: 1, Xt: 0, R: "", Vt: false }, _t: 0, ut: 0 }, this.Gt = new E(this.Zt), this.Jt = t, this.Pt = i;
    }
    yt() {
      this.xt = true;
    }
    Tt(t) {
      return this.xt && (this.Rt(), this.xt = false), this.Gt;
    }
    Rt() {
      const t = this.Jt.Vt(), i = this.Pt.Qt().N().crosshair, s = this.Zt;
      if (2 === i.mode) return s.Kt.Vt = false, void (s.jt.Vt = false);
      s.Kt.Vt = t && this.Jt.ti(this.Pt), s.jt.Vt = t && this.Jt.ii(), s.Kt.ct = i.horzLine.width, s.Kt.Xt = i.horzLine.style, s.Kt.R = i.horzLine.color, s.jt.ct = i.vertLine.width, s.jt.Xt = i.vertLine.style, s.jt.R = i.vertLine.color, s._t = this.Jt.si(), s.ut = this.Jt.ni();
    }
  };
  function z(t, i, s, n, e3, r2) {
    t.fillRect(i + r2, s, n - 2 * r2, r2), t.fillRect(i + r2, s + e3 - r2, n - 2 * r2, r2), t.fillRect(i, s, r2, e3), t.fillRect(i + n - r2, s, r2, e3);
  }
  function L(t, i, s, n, e3, r2) {
    t.save(), t.globalCompositeOperation = "copy", t.fillStyle = r2, t.fillRect(i, s, n, e3), t.restore();
  }
  function O(t, i, s, n, e3, r2) {
    t.beginPath(), t.roundRect ? t.roundRect(i, s, n, e3, r2) : (t.lineTo(i + n - r2[1], s), 0 !== r2[1] && t.arcTo(i + n, s, i + n, s + r2[1], r2[1]), t.lineTo(i + n, s + e3 - r2[2]), 0 !== r2[2] && t.arcTo(i + n, s + e3, i + n - r2[2], s + e3, r2[2]), t.lineTo(i + r2[3], s + e3), 0 !== r2[3] && t.arcTo(i, s + e3, i, s + e3 - r2[3], r2[3]), t.lineTo(i, s + r2[0]), 0 !== r2[0] && t.arcTo(i, s, i + r2[0], s, r2[0]));
  }
  function N(t, i, s, n, e3, r2, h2 = 0, a2 = [0, 0, 0, 0], l2 = "") {
    if (t.save(), !h2 || !l2 || l2 === r2) return O(t, i, s, n, e3, a2), t.fillStyle = r2, t.fill(), void t.restore();
    const o2 = h2 / 2;
    var _2;
    O(t, i + o2, s + o2, n - h2, e3 - h2, (_2 = -o2, a2.map(((t2) => 0 === t2 ? t2 : t2 + _2)))), "transparent" !== r2 && (t.fillStyle = r2, t.fill()), "transparent" !== l2 && (t.lineWidth = h2, t.strokeStyle = l2, t.closePath(), t.stroke()), t.restore();
  }
  function F(t, i, s, n, e3, r2, h2) {
    t.save(), t.globalCompositeOperation = "copy";
    const a2 = t.createLinearGradient(0, 0, 0, e3);
    a2.addColorStop(0, r2), a2.addColorStop(1, h2), t.fillStyle = a2, t.fillRect(i, s, n, e3), t.restore();
  }
  var W = class {
    constructor(t, i) {
      this.ht(t, i);
    }
    ht(t, i) {
      this.Yt = t, this.ei = i;
    }
    $t(t, i) {
      return this.Yt.Vt ? t.P + t.A + t.V : 0;
    }
    nt(t, i, s, n) {
      if (!this.Yt.Vt || 0 === this.Yt.ri.length) return;
      const e3 = this.Yt.R, r2 = this.ei.Z, h2 = t.useBitmapCoordinateSpace(((t2) => {
        const h3 = t2.context;
        h3.font = i.k;
        const a2 = this.hi(t2, i, s, n), l2 = a2.ai;
        return a2.li ? N(h3, l2.oi, l2._i, l2.ui, l2.ci, r2, l2.di, [l2.ft, 0, 0, l2.ft], r2) : N(h3, l2.fi, l2._i, l2.ui, l2.ci, r2, l2.di, [0, l2.ft, l2.ft, 0], r2), this.Yt.pi && (h3.fillStyle = e3, h3.fillRect(l2.fi, l2.mi, l2.wi - l2.fi, l2.gi)), this.Yt.Mi && (h3.fillStyle = i.D, h3.fillRect(a2.li ? l2.bi - l2.di : 0, l2._i, l2.di, l2.Si - l2._i)), a2;
      }));
      t.useMediaCoordinateSpace((({ context: t2 }) => {
        const s2 = h2.xi;
        t2.font = i.k, t2.textAlign = h2.li ? "right" : "left", t2.textBaseline = "middle", t2.fillStyle = e3, t2.fillText(this.Yt.ri, s2.Ci, (s2._i + s2.Si) / 2 + s2.Pi);
      }));
    }
    hi(t, i, s, n) {
      const { context: e3, bitmapSize: r2, mediaSize: h2, horizontalPixelRatio: a2, verticalPixelRatio: l2 } = t, o2 = this.Yt.pi || !this.Yt.yi ? i.C : 0, _2 = this.Yt.ki ? i.S : 0, u2 = i.A + this.ei.Ti, c2 = i.V + this.ei.Ri, d2 = i.B, f2 = i.I, p2 = this.Yt.ri, v2 = i.P, m2 = s.Di(e3, p2), w2 = Math.ceil(s.Vi(e3, p2)), g2 = v2 + u2 + c2, M2 = i.S + d2 + f2 + w2 + o2, b2 = Math.max(1, Math.floor(l2));
      let S2 = Math.round(g2 * l2);
      S2 % 2 != b2 % 2 && (S2 += 1);
      const x3 = _2 > 0 ? Math.max(1, Math.floor(_2 * a2)) : 0, C2 = Math.round(M2 * a2), P2 = Math.round(o2 * a2), y3 = this.ei.Bi ?? this.ei.Ii, k2 = Math.round(y3 * l2) - Math.floor(0.5 * l2), T2 = Math.floor(k2 + b2 / 2 - S2 / 2), R2 = T2 + S2, D2 = "right" === n, V2 = D2 ? h2.width - _2 : _2, B2 = D2 ? r2.width - x3 : x3;
      let I2, E2, A2;
      return D2 ? (I2 = B2 - C2, E2 = B2 - P2, A2 = V2 - o2 - d2 - _2) : (I2 = B2 + C2, E2 = B2 + P2, A2 = V2 + o2 + d2), { li: D2, ai: { _i: T2, mi: k2, Si: R2, ui: C2, ci: S2, ft: 2 * a2, di: x3, oi: I2, fi: B2, wi: E2, gi: b2, bi: r2.width }, xi: { _i: T2 / l2, Si: R2 / l2, Ci: A2, Pi: m2 } };
    }
  };
  var H = class {
    constructor(t) {
      this.Ei = { Ii: 0, Z: "#000", Ri: 0, Ti: 0 }, this.Ai = { ri: "", Vt: false, pi: true, yi: false, Ht: "", R: "#FFF", Mi: false, ki: false }, this.zi = { ri: "", Vt: false, pi: false, yi: true, Ht: "", R: "#FFF", Mi: true, ki: true }, this.xt = true, this.Li = new (t || W)(this.Ai, this.Ei), this.Oi = new (t || W)(this.zi, this.Ei);
    }
    ri() {
      return this.Ni(), this.Ai.ri;
    }
    Ii() {
      return this.Ni(), this.Ei.Ii;
    }
    yt() {
      this.xt = true;
    }
    $t(t, i = false) {
      return Math.max(this.Li.$t(t, i), this.Oi.$t(t, i));
    }
    Fi() {
      return this.Ei.Bi || 0;
    }
    Wi(t) {
      this.Ei.Bi = t;
    }
    Hi() {
      return this.Ni(), this.Ai.Vt || this.zi.Vt;
    }
    Ui() {
      return this.Ni(), this.Ai.Vt;
    }
    Tt(t) {
      return this.Ni(), this.Ai.pi = this.Ai.pi && t.N().ticksVisible, this.zi.pi = this.zi.pi && t.N().ticksVisible, this.Li.ht(this.Ai, this.Ei), this.Oi.ht(this.zi, this.Ei), this.Li;
    }
    $i() {
      return this.Ni(), this.Li.ht(this.Ai, this.Ei), this.Oi.ht(this.zi, this.Ei), this.Oi;
    }
    Ni() {
      this.xt && (this.Ai.pi = true, this.zi.pi = false, this.qi(this.Ai, this.zi, this.Ei));
    }
  };
  var U = class extends H {
    constructor(t, i, s) {
      super(), this.Jt = t, this.Yi = i, this.ji = s;
    }
    qi(t, i, s) {
      if (t.Vt = false, 2 === this.Jt.N().mode) return;
      const n = this.Jt.N().horzLine;
      if (!n.labelVisible) return;
      const e3 = this.Yi.zt();
      if (!this.Jt.Vt() || this.Yi.Ki() || null === e3) return;
      const r2 = this.Yi.Xi().X(n.labelBackgroundColor);
      s.Z = r2.Z, t.R = r2.G;
      const h2 = 2 / 12 * this.Yi.P();
      s.Ti = h2, s.Ri = h2;
      const a2 = this.ji(this.Yi);
      s.Ii = a2.Ii, t.ri = this.Yi.Zi(a2.gt, e3), t.Vt = true;
    }
  };
  var $ = /[1-9]/g;
  var q = class {
    constructor() {
      this.Yt = null;
    }
    ht(t) {
      this.Yt = t;
    }
    nt(t, i) {
      if (null === this.Yt || false === this.Yt.Vt || 0 === this.Yt.ri.length) return;
      const s = t.useMediaCoordinateSpace((({ context: t2 }) => (t2.font = i.k, Math.round(i.Gi.Vi(t2, u(this.Yt).ri, $)))));
      if (s <= 0) return;
      const n = i.Ji, e3 = s + 2 * n, r2 = e3 / 2, h2 = this.Yt.Qi;
      let a2 = this.Yt.Ii, l2 = Math.floor(a2 - r2) + 0.5;
      l2 < 0 ? (a2 += Math.abs(0 - l2), l2 = Math.floor(a2 - r2) + 0.5) : l2 + e3 > h2 && (a2 -= Math.abs(h2 - (l2 + e3)), l2 = Math.floor(a2 - r2) + 0.5);
      const o2 = l2 + e3, _2 = Math.ceil(0 + i.S + i.C + i.A + i.P + i.V);
      t.useBitmapCoordinateSpace((({ context: t2, horizontalPixelRatio: s2, verticalPixelRatio: n2 }) => {
        const e4 = u(this.Yt);
        t2.fillStyle = e4.Z;
        const r3 = Math.round(l2 * s2), h3 = Math.round(0 * n2), a3 = Math.round(o2 * s2), c2 = Math.round(_2 * n2), d2 = Math.round(2 * s2);
        if (t2.beginPath(), t2.moveTo(r3, h3), t2.lineTo(r3, c2 - d2), t2.arcTo(r3, c2, r3 + d2, c2, d2), t2.lineTo(a3 - d2, c2), t2.arcTo(a3, c2, a3, c2 - d2, d2), t2.lineTo(a3, h3), t2.fill(), e4.pi) {
          const r4 = Math.round(e4.Ii * s2), a4 = h3, l3 = Math.round((a4 + i.C) * n2);
          t2.fillStyle = e4.R;
          const o3 = Math.max(1, Math.floor(s2)), _3 = Math.floor(0.5 * s2);
          t2.fillRect(r4 - _3, a4, o3, l3 - a4);
        }
      })), t.useMediaCoordinateSpace((({ context: t2 }) => {
        const s2 = u(this.Yt), e4 = 0 + i.S + i.C + i.A + i.P / 2;
        t2.font = i.k, t2.textAlign = "left", t2.textBaseline = "middle", t2.fillStyle = s2.R;
        const r3 = i.Gi.Di(t2, "Apr0");
        t2.translate(l2 + n, e4 + r3), t2.fillText(s2.ri, 0, 0);
      }));
    }
  };
  var Y = class {
    constructor(t, i, s) {
      this.xt = true, this.Gt = new q(), this.Zt = { Vt: false, Z: "#4c525e", R: "white", ri: "", Qi: 0, Ii: NaN, pi: true }, this.Ct = t, this.ts = i, this.ji = s;
    }
    yt() {
      this.xt = true;
    }
    Tt() {
      return this.xt && (this.Rt(), this.xt = false), this.Gt.ht(this.Zt), this.Gt;
    }
    Rt() {
      const t = this.Zt;
      if (t.Vt = false, 2 === this.Ct.N().mode) return;
      const i = this.Ct.N().vertLine;
      if (!i.labelVisible) return;
      const s = this.ts.Et();
      if (s.Ki()) return;
      t.Qi = s.Qi();
      const n = this.ji();
      if (null === n) return;
      t.Ii = n.Ii;
      const e3 = s.ss(this.Ct.It());
      t.ri = s.ns(u(e3)), t.Vt = true;
      const r2 = this.ts.Xi().X(i.labelBackgroundColor);
      t.Z = r2.Z, t.R = r2.G, t.pi = s.N().ticksVisible;
    }
  };
  var j = class {
    constructor() {
      this.es = null, this.rs = 0;
    }
    hs() {
      return this.rs;
    }
    ls(t) {
      this.rs = t;
    }
    Ft() {
      return this.es;
    }
    _s(t) {
      this.es = t;
    }
    us(t) {
      return [];
    }
    cs() {
      return [];
    }
    Vt() {
      return true;
    }
  };
  var K;
  !(function(t) {
    t[t.Normal = 0] = "Normal", t[t.Magnet = 1] = "Magnet", t[t.Hidden = 2] = "Hidden", t[t.MagnetOHLC = 3] = "MagnetOHLC";
  })(K || (K = {}));
  var X = class extends j {
    constructor(t, i) {
      super(), this.Pt = null, this.ds = NaN, this.fs = 0, this.ps = false, this.vs = /* @__PURE__ */ new Map(), this.ws = false, this.gs = /* @__PURE__ */ new WeakMap(), this.Ms = /* @__PURE__ */ new WeakMap(), this.bs = NaN, this.Ss = NaN, this.xs = NaN, this.Cs = NaN, this.ts = t, this.Ps = i;
      this.ys = /* @__PURE__ */ ((t2, i2) => (s2) => {
        const n = i2(), e3 = t2();
        if (s2 === u(this.Pt).ks()) return { gt: e3, Ii: n };
        {
          const t3 = u(s2.zt());
          return { gt: s2.Ts(n, t3), Ii: n };
        }
      })((() => this.ds), (() => this.Ss));
      const s = /* @__PURE__ */ ((t2, i2) => () => {
        const s2 = this.ts.Et().Rs(t2()), n = i2();
        return s2 && Number.isFinite(n) ? { wt: s2, Ii: n } : null;
      })((() => this.fs), (() => this.si()));
      this.Ds = new Y(this, t, s);
    }
    N() {
      return this.Ps;
    }
    Vs(t, i) {
      this.xs = t, this.Cs = i;
    }
    Bs() {
      this.xs = NaN, this.Cs = NaN;
    }
    Is() {
      return this.xs;
    }
    Es() {
      return this.Cs;
    }
    As(t, i, s) {
      this.ws || (this.ws = true), this.ps = true, this.zs(t, i, s);
    }
    It() {
      return this.fs;
    }
    si() {
      return this.bs;
    }
    ni() {
      return this.Ss;
    }
    Vt() {
      return this.ps;
    }
    Ls() {
      this.ps = false, this.Os(), this.ds = NaN, this.bs = NaN, this.Ss = NaN, this.Pt = null, this.Bs(), this.Ns();
    }
    Fs(t) {
      let i = this.gs.get(t);
      i || (i = new A(this, t), this.gs.set(t, i));
      let s = this.Ms.get(t);
      return s || (s = new I(this.ts, this, t), this.Ms.set(t, s)), [i, s];
    }
    ti(t) {
      return t === this.Pt && this.Ps.horzLine.visible;
    }
    ii() {
      return this.Ps.vertLine.visible;
    }
    Ws(t, i) {
      this.ps && this.Pt === t || this.vs.clear();
      const s = [];
      return this.Pt === t && s.push(this.Hs(this.vs, i, this.ys)), s;
    }
    cs() {
      return this.ps ? [this.Ds] : [];
    }
    Us() {
      return this.Pt;
    }
    Ns() {
      this.ts.$s().forEach(((t) => {
        this.gs.get(t)?.yt(), this.Ms.get(t)?.yt();
      })), this.vs.forEach(((t) => t.yt())), this.Ds.yt();
    }
    qs(t) {
      return t && !t.ks().Ki() ? t.ks() : null;
    }
    zs(t, i, s) {
      this.Ys(t, i, s) && this.Ns();
    }
    Ys(t, i, s) {
      const n = this.bs, e3 = this.Ss, r2 = this.ds, h2 = this.fs, a2 = this.Pt, l2 = this.qs(s);
      this.fs = t, this.bs = isNaN(t) ? NaN : this.ts.Et().qt(t), this.Pt = s;
      const o2 = null !== l2 ? l2.zt() : null;
      return null !== l2 && null !== o2 ? (this.ds = i, this.Ss = l2.Nt(i, o2)) : (this.ds = NaN, this.Ss = NaN), n !== this.bs || e3 !== this.Ss || h2 !== this.fs || r2 !== this.ds || a2 !== this.Pt;
    }
    Os() {
      const t = this.ts.js().map(((t2) => t2.Xs().Ks())).filter(M), i = 0 === t.length ? null : Math.max(...t);
      this.fs = null !== i ? i : NaN;
    }
    Hs(t, i, s) {
      let n = t.get(i);
      return void 0 === n && (n = new U(this, i, s), t.set(i, n)), n;
    }
  };
  function Z(t) {
    return "left" === t || "right" === t;
  }
  var G = class _G {
    constructor(t) {
      this.Zs = /* @__PURE__ */ new Map(), this.Gs = [], this.Js = t;
    }
    Qs(t, i) {
      const s = (function(t2, i2) {
        return void 0 === t2 ? i2 : { tn: Math.max(t2.tn, i2.tn), sn: t2.sn || i2.sn };
      })(this.Zs.get(t), i);
      this.Zs.set(t, s);
    }
    nn() {
      return this.Js;
    }
    en(t) {
      const i = this.Zs.get(t);
      return void 0 === i ? { tn: this.Js } : { tn: Math.max(this.Js, i.tn), sn: i.sn };
    }
    rn() {
      this.hn(), this.Gs = [{ an: 0 }];
    }
    ln(t) {
      this.hn(), this.Gs = [{ an: 1, Wt: t }];
    }
    _n(t) {
      this.un(), this.Gs.push({ an: 5, Wt: t });
    }
    hn() {
      this.un(), this.Gs.push({ an: 6 });
    }
    cn() {
      this.hn(), this.Gs = [{ an: 4 }];
    }
    dn(t) {
      this.hn(), this.Gs.push({ an: 2, Wt: t });
    }
    fn(t) {
      this.hn(), this.Gs.push({ an: 3, Wt: t });
    }
    pn() {
      return this.Gs;
    }
    vn(t) {
      for (const i of t.Gs) this.mn(i);
      this.Js = Math.max(this.Js, t.Js), t.Zs.forEach(((t2, i) => {
        this.Qs(i, t2);
      }));
    }
    static wn() {
      return new _G(2);
    }
    static gn() {
      return new _G(3);
    }
    mn(t) {
      switch (t.an) {
        case 0:
          this.rn();
          break;
        case 1:
          this.ln(t.Wt);
          break;
        case 2:
          this.dn(t.Wt);
          break;
        case 3:
          this.fn(t.Wt);
          break;
        case 4:
          this.cn();
          break;
        case 5:
          this._n(t.Wt);
          break;
        case 6:
          this.un();
      }
    }
    un() {
      const t = this.Gs.findIndex(((t2) => 5 === t2.an));
      -1 !== t && this.Gs.splice(t, 1);
    }
  };
  var J = class {
    formatTickmarks(t) {
      return t.map(((t2) => this.format(t2)));
    }
  };
  var Q = ".";
  function tt(t, i) {
    if (!p(t)) return "n/a";
    if (!v(i)) throw new TypeError("invalid length");
    if (i < 0 || i > 16) throw new TypeError("invalid length");
    if (0 === i) return t.toString();
    return ("0000000000000000" + t.toString()).slice(-i);
  }
  var it = class extends J {
    constructor(t, i) {
      if (super(), i || (i = 1), p(t) && v(t) || (t = 100), t < 0) throw new TypeError("invalid base");
      this.Yi = t, this.Mn = i, this.bn();
    }
    format(t) {
      const i = t < 0 ? "\u2212" : "";
      return t = Math.abs(t), i + this.Sn(t);
    }
    bn() {
      if (this.xn = 0, this.Yi > 0 && this.Mn > 0) {
        let t = this.Yi;
        for (; t > 1; ) t /= 10, this.xn++;
      }
    }
    Sn(t) {
      const i = this.Yi / this.Mn;
      let s = Math.floor(t), n = "";
      const e3 = void 0 !== this.xn ? this.xn : NaN;
      if (i > 1) {
        let r2 = +(Math.round(t * i) - s * i).toFixed(this.xn);
        r2 >= i && (r2 -= i, s += 1), n = Q + tt(+r2.toFixed(this.xn) * this.Mn, e3);
      } else s = Math.round(s * i) / i, e3 > 0 && (n = Q + tt(0, e3));
      return s.toFixed(0) + n;
    }
  };
  var st = class extends it {
    constructor(t = 100) {
      super(t);
    }
    format(t) {
      return `${super.format(t)}%`;
    }
  };
  var nt = class extends J {
    constructor(t) {
      super(), this.Cn = t;
    }
    format(t) {
      let i = "";
      return t < 0 && (i = "-", t = -t), t < 995 ? i + this.Pn(t) : t < 999995 ? i + this.Pn(t / 1e3) + "K" : t < 999999995 ? (t = 1e3 * Math.round(t / 1e3), i + this.Pn(t / 1e6) + "M") : (t = 1e6 * Math.round(t / 1e6), i + this.Pn(t / 1e9) + "B");
    }
    Pn(t) {
      let i;
      const s = Math.pow(10, this.Cn);
      return i = (t = Math.round(t * s) / s) >= 1e-15 && t < 1 ? t.toFixed(this.Cn).replace(/\.?0+$/, "") : String(t), i.replace(/(\.[1-9]*)0+$/, ((t2, i2) => i2));
    }
  };
  var et = /[2-9]/g;
  var rt = class {
    constructor(t = 50) {
      this.yn = 0, this.kn = 1, this.Tn = 1, this.Rn = {}, this.Dn = /* @__PURE__ */ new Map(), this.Vn = t;
    }
    Bn() {
      this.yn = 0, this.Dn.clear(), this.kn = 1, this.Tn = 1, this.Rn = {};
    }
    Vi(t, i, s) {
      return this.In(t, i, s).width;
    }
    Di(t, i, s) {
      const n = this.In(t, i, s);
      return ((n.actualBoundingBoxAscent || 0) - (n.actualBoundingBoxDescent || 0)) / 2;
    }
    In(t, i, s) {
      const n = s || et, e3 = String(i).replace(n, "0");
      if (this.Dn.has(e3)) return _(this.Dn.get(e3)).En;
      if (this.yn === this.Vn) {
        const t2 = this.Rn[this.Tn];
        delete this.Rn[this.Tn], this.Dn.delete(t2), this.Tn++, this.yn--;
      }
      t.save(), t.textBaseline = "middle";
      const r2 = t.measureText(e3);
      return t.restore(), 0 === r2.width && i.length || (this.Dn.set(e3, { En: r2, An: this.kn }), this.Rn[this.kn] = e3, this.yn++, this.kn++), r2;
    }
  };
  var ht = class {
    constructor(t) {
      this.zn = null, this.M = null, this.Ln = "right", this.On = t;
    }
    Nn(t, i, s) {
      this.zn = t, this.M = i, this.Ln = s;
    }
    nt(t) {
      null !== this.M && null !== this.zn && this.zn.nt(t, this.M, this.On, this.Ln);
    }
  };
  var at = class {
    constructor(t, i, s) {
      this.Fn = t, this.On = new rt(50), this.Wn = i, this.O = s, this.F = -1, this.Gt = new ht(this.On);
    }
    Tt() {
      const t = this.O.Hn(this.Wn);
      if (null === t) return null;
      const i = t.Un(this.Wn) ? t.$n() : this.Wn.Ft();
      if (null === i) return null;
      const s = t.qn(i);
      if ("overlay" === s) return null;
      const n = this.O.Yn();
      return n.P !== this.F && (this.F = n.P, this.On.Bn()), this.Gt.Nn(this.Fn.$i(), n, s), this.Gt;
    }
  };
  var lt = class extends R {
    constructor() {
      super(...arguments), this.Yt = null;
    }
    ht(t) {
      this.Yt = t;
    }
    jn(t, i) {
      if (!this.Yt?.Vt) return null;
      const { ut: s, ct: n, Kn: e3 } = this.Yt;
      return i >= s - n - 7 && i <= s + n + 7 ? { Xn: this.Yt, Kn: e3 } : null;
    }
    et({ context: t, bitmapSize: i, horizontalPixelRatio: s, verticalPixelRatio: n }) {
      if (null === this.Yt) return;
      if (false === this.Yt.Vt) return;
      const e3 = Math.round(this.Yt.ut * n);
      e3 < 0 || e3 > i.height || (t.lineCap = "butt", t.strokeStyle = this.Yt.R, t.lineWidth = Math.floor(this.Yt.ct * s), a(t, this.Yt.Xt), l(t, e3, 0, i.width));
    }
  };
  var ot = class {
    constructor(t) {
      this.Zn = { ut: 0, R: "rgba(0, 0, 0, 0)", ct: 1, Xt: 0, Vt: false }, this.Gn = new lt(), this.xt = true, this.Jn = t, this.Qn = t.Qt(), this.Gn.ht(this.Zn);
    }
    yt() {
      this.xt = true;
    }
    Tt() {
      return this.Jn.Vt() ? (this.xt && (this.te(), this.xt = false), this.Gn) : null;
    }
  };
  var _t = class extends ot {
    constructor(t) {
      super(t);
    }
    te() {
      this.Zn.Vt = false;
      const t = this.Jn.Ft(), i = t.ie().ie;
      if (2 !== i && 3 !== i) return;
      const s = this.Jn.N();
      if (!s.baseLineVisible || !this.Jn.Vt()) return;
      const n = this.Jn.zt();
      null !== n && (this.Zn.Vt = true, this.Zn.ut = t.Nt(n.Wt, n.Wt), this.Zn.R = s.baseLineColor, this.Zn.ct = s.baseLineWidth, this.Zn.Xt = s.baseLineStyle);
    }
  };
  var ut = class extends R {
    constructor() {
      super(...arguments), this.Yt = null;
    }
    ht(t) {
      this.Yt = t;
    }
    se() {
      return this.Yt;
    }
    et({ context: t, horizontalPixelRatio: i, verticalPixelRatio: s }) {
      const n = this.Yt;
      if (null === n) return;
      const e3 = Math.max(1, Math.floor(i)), r2 = e3 % 2 / 2, h2 = Math.round(n.ne.x * i) + r2, a2 = n.ne.y * s;
      t.fillStyle = n.ee, t.beginPath();
      const l2 = Math.max(2, 1.5 * n.re) * i;
      t.arc(h2, a2, l2, 0, 2 * Math.PI, false), t.fill(), t.fillStyle = n.he, t.beginPath(), t.arc(h2, a2, n.ft * i, 0, 2 * Math.PI, false), t.fill(), t.lineWidth = e3, t.strokeStyle = n.ae, t.beginPath(), t.arc(h2, a2, n.ft * i + e3 / 2, 0, 2 * Math.PI, false), t.stroke();
    }
  };
  var ct = [{ le: 0, oe: 0.25, _e: 4, ue: 10, ce: 0.25, de: 0, fe: 0.4, pe: 0.8 }, { le: 0.25, oe: 0.525, _e: 10, ue: 14, ce: 0, de: 0, fe: 0.8, pe: 0 }, { le: 0.525, oe: 1, _e: 14, ue: 14, ce: 0, de: 0, fe: 0, pe: 0 }];
  var dt = class {
    constructor(t) {
      this.Gt = new ut(), this.xt = true, this.ve = true, this.me = performance.now(), this.we = this.me - 1, this.ge = t;
    }
    Me() {
      this.we = this.me - 1, this.yt();
    }
    be() {
      if (this.yt(), 2 === this.ge.N().lastPriceAnimation) {
        const t = performance.now(), i = this.we - t;
        if (i > 0) return void (i < 650 && (this.we += 2600));
        this.me = t, this.we = t + 2600;
      }
    }
    yt() {
      this.xt = true;
    }
    Se() {
      this.ve = true;
    }
    Vt() {
      return 0 !== this.ge.N().lastPriceAnimation;
    }
    xe() {
      switch (this.ge.N().lastPriceAnimation) {
        case 0:
          return false;
        case 1:
          return true;
        case 2:
          return performance.now() <= this.we;
      }
    }
    Tt() {
      return this.xt ? (this.Rt(), this.xt = false, this.ve = false) : this.ve && (this.Ce(), this.ve = false), this.Gt;
    }
    Rt() {
      this.Gt.ht(null);
      const t = this.ge.Qt().Et(), i = t.Pe(), s = this.ge.zt();
      if (null === i || null === s) return;
      const n = this.ge.ye(true);
      if (n.ke || !i.Te(n.Re)) return;
      const e3 = { x: t.qt(n.Re), y: this.ge.Ft().Nt(n.gt, s.Wt) }, r2 = n.R, h2 = this.ge.N().lineWidth, a2 = this.De(this.Ve(), r2);
      this.Gt.ht({ ee: r2, re: h2, he: a2.he, ae: a2.ae, ft: a2.ft, ne: e3 });
    }
    Ce() {
      const t = this.Gt.se();
      if (null !== t) {
        const i = this.De(this.Ve(), t.ee);
        t.he = i.he, t.ae = i.ae, t.ft = i.ft;
      }
    }
    Ve() {
      return this.xe() ? performance.now() - this.me : 2599;
    }
    Be(t, i, s, n) {
      const e3 = s + (n - s) * i;
      return this.ge.Qt().Xi().j(t, e3);
    }
    De(t, i) {
      const s = t % 2600 / 2600;
      let n;
      for (const t2 of ct) if (s >= t2.le && s <= t2.oe) {
        n = t2;
        break;
      }
      o(void 0 !== n, "Last price animation internal logic error");
      const e3 = (s - n.le) / (n.oe - n.le);
      return { he: this.Be(i, e3, n.ce, n.de), ae: this.Be(i, e3, n.fe, n.pe), ft: (r2 = e3, h2 = n._e, a2 = n.ue, h2 + (a2 - h2) * r2) };
      var r2, h2, a2;
    }
  };
  var ft = class extends ot {
    constructor(t) {
      super(t);
    }
    te() {
      const t = this.Zn;
      t.Vt = false;
      const i = this.Jn.N();
      if (!i.priceLineVisible || !this.Jn.Vt()) return;
      const s = this.Jn.ye(0 === i.priceLineSource);
      s.ke || (t.Vt = true, t.ut = s.Ii, t.R = this.Jn.Ie(s.R), t.ct = i.priceLineWidth, t.Xt = i.priceLineStyle);
    }
  };
  var pt = class extends H {
    constructor(t) {
      super(), this.Jt = t;
    }
    qi(t, i, s) {
      t.Vt = false, i.Vt = false;
      const n = this.Jt;
      if (!n.Vt()) return;
      const e3 = n.N(), r2 = e3.lastValueVisible, h2 = "" !== n.Ee(), a2 = 0 === e3.seriesLastValueMode, l2 = n.ye(false);
      if (l2.ke) return;
      r2 && (t.ri = this.Ae(l2, r2, a2), t.Vt = 0 !== t.ri.length), (h2 || a2) && (i.ri = this.ze(l2, r2, h2, a2), i.Vt = i.ri.length > 0);
      const o2 = n.Ie(l2.R), _2 = this.Jt.Qt().Xi().X(o2);
      s.Z = _2.Z, s.Ii = l2.Ii, i.Ht = n.Qt().Ut(l2.Ii / n.Ft().$t()), t.Ht = o2, t.R = _2.G, i.R = _2.G;
    }
    ze(t, i, s, n) {
      let e3 = "";
      const r2 = this.Jt.Ee();
      return s && 0 !== r2.length && (e3 += `${r2} `), i && n && (e3 += this.Jt.Ft().Le() ? t.Oe : t.Ne), e3.trim();
    }
    Ae(t, i, s) {
      return i ? s ? this.Jt.Ft().Le() ? t.Ne : t.Oe : t.ri : "";
    }
  };
  function vt(t, i, s, n) {
    const e3 = Number.isFinite(i), r2 = Number.isFinite(s);
    return e3 && r2 ? t(i, s) : e3 || r2 ? e3 ? i : s : n;
  }
  var mt = class _mt {
    constructor(t, i) {
      this.Fe = t, this.We = i;
    }
    He(t) {
      return null !== t && (this.Fe === t.Fe && this.We === t.We);
    }
    Ue() {
      return new _mt(this.Fe, this.We);
    }
    $e() {
      return this.Fe;
    }
    qe() {
      return this.We;
    }
    Ye() {
      return this.We - this.Fe;
    }
    Ki() {
      return this.We === this.Fe || Number.isNaN(this.We) || Number.isNaN(this.Fe);
    }
    vn(t) {
      return null === t ? this : new _mt(vt(Math.min, this.$e(), t.$e(), -1 / 0), vt(Math.max, this.qe(), t.qe(), 1 / 0));
    }
    je(t) {
      if (!p(t)) return;
      if (0 === this.We - this.Fe) return;
      const i = 0.5 * (this.We + this.Fe);
      let s = this.We - i, n = this.Fe - i;
      s *= t, n *= t, this.We = i + s, this.Fe = i + n;
    }
    Ke(t) {
      p(t) && (this.We += t, this.Fe += t);
    }
    Xe() {
      return { minValue: this.Fe, maxValue: this.We };
    }
    static Ze(t) {
      return null === t ? null : new _mt(t.minValue, t.maxValue);
    }
  };
  var wt = class _wt {
    constructor(t, i) {
      this.Ge = t, this.Je = i || null;
    }
    Qe() {
      return this.Ge;
    }
    tr() {
      return this.Je;
    }
    Xe() {
      return { priceRange: null === this.Ge ? null : this.Ge.Xe(), margins: this.Je || void 0 };
    }
    static Ze(t) {
      return null === t ? null : new _wt(mt.Ze(t.priceRange), t.margins);
    }
  };
  var gt = class extends ot {
    constructor(t, i) {
      super(t), this.ir = i;
    }
    te() {
      const t = this.Zn;
      t.Vt = false;
      const i = this.ir.N();
      if (!this.Jn.Vt() || !i.lineVisible) return;
      const s = this.ir.sr();
      null !== s && (t.Vt = true, t.ut = s, t.R = i.color, t.ct = i.lineWidth, t.Xt = i.lineStyle, t.Kn = this.ir.N().id);
    }
  };
  var Mt = class extends H {
    constructor(t, i) {
      super(), this.ge = t, this.ir = i;
    }
    qi(t, i, s) {
      t.Vt = false, i.Vt = false;
      const n = this.ir.N(), e3 = n.axisLabelVisible, r2 = "" !== n.title, h2 = this.ge;
      if (!e3 || !h2.Vt()) return;
      const a2 = this.ir.sr();
      if (null === a2) return;
      r2 && (i.ri = n.title, i.Vt = true), i.Ht = h2.Qt().Ut(a2 / h2.Ft().$t()), t.ri = this.nr(n.price), t.Vt = true;
      const l2 = this.ge.Qt().Xi().X(n.axisLabelColor || n.color);
      s.Z = l2.Z;
      const o2 = n.axisLabelTextColor || l2.G;
      t.R = o2, i.R = o2, s.Ii = a2;
    }
    nr(t) {
      const i = this.ge.zt();
      return null === i ? "" : this.ge.Ft().Zi(t, i.Wt);
    }
  };
  var bt = class {
    constructor(t, i) {
      this.ge = t, this.Ps = i, this.er = new gt(t, this), this.Fn = new Mt(t, this), this.rr = new at(this.Fn, t, t.Qt());
    }
    hr(t) {
      f(this.Ps, t), this.yt(), this.ge.Qt().ar();
    }
    N() {
      return this.Ps;
    }
    lr() {
      return this.er;
    }
    _r() {
      return this.rr;
    }
    ur() {
      return this.Fn;
    }
    yt() {
      this.er.yt(), this.Fn.yt();
    }
    sr() {
      const t = this.ge, i = t.Ft();
      if (t.Qt().Et().Ki() || i.Ki()) return null;
      const s = t.zt();
      return null === s ? null : i.Nt(this.Ps.price, s.Wt);
    }
  };
  var St = class extends j {
    constructor(t) {
      super(), this.ts = t;
    }
    Qt() {
      return this.ts;
    }
  };
  var xt = { Bar: (t, i, s, n) => {
    const e3 = i.upColor, r2 = i.downColor, h2 = u(t(s, n)), a2 = c(h2.Wt[0]) <= c(h2.Wt[3]);
    return { cr: h2.R ?? (a2 ? e3 : r2) };
  }, Candlestick: (t, i, s, n) => {
    const e3 = i.upColor, r2 = i.downColor, h2 = i.borderUpColor, a2 = i.borderDownColor, l2 = i.wickUpColor, o2 = i.wickDownColor, _2 = u(t(s, n)), d2 = c(_2.Wt[0]) <= c(_2.Wt[3]);
    return { cr: _2.R ?? (d2 ? e3 : r2), dr: _2.Ht ?? (d2 ? h2 : a2), pr: _2.vr ?? (d2 ? l2 : o2) };
  }, Custom: (t, i, s, n) => ({ cr: u(t(s, n)).R ?? i.color }), Area: (t, i, s, n) => {
    const e3 = u(t(s, n));
    return { cr: e3.vt ?? i.lineColor, vt: e3.vt ?? i.lineColor, mr: e3.mr ?? i.topColor, wr: e3.wr ?? i.bottomColor };
  }, Baseline: (t, i, s, n) => {
    const e3 = u(t(s, n));
    return { cr: e3.Wt[3] >= i.baseValue.price ? i.topLineColor : i.bottomLineColor, gr: e3.gr ?? i.topLineColor, Mr: e3.Mr ?? i.bottomLineColor, br: e3.br ?? i.topFillColor1, Sr: e3.Sr ?? i.topFillColor2, Cr: e3.Cr ?? i.bottomFillColor1, Pr: e3.Pr ?? i.bottomFillColor2 };
  }, Line: (t, i, s, n) => {
    const e3 = u(t(s, n));
    return { cr: e3.R ?? i.color, vt: e3.R ?? i.color };
  }, Histogram: (t, i, s, n) => ({ cr: u(t(s, n)).R ?? i.color }) };
  var Ct = class {
    constructor(t) {
      this.yr = (t2, i) => void 0 !== i ? i.Wt : this.ge.Xs().kr(t2), this.ge = t, this.Tr = xt[t.Rr()];
    }
    Dr(t, i) {
      return this.Tr(this.yr, this.ge.N(), t, i);
    }
  };
  function Pt(t, i, s, n, e3 = 0, r2 = i.length) {
    let h2 = r2 - e3;
    for (; 0 < h2; ) {
      const r3 = h2 >> 1, a2 = e3 + r3;
      n(i[a2], s) === t ? (e3 = a2 + 1, h2 -= r3 + 1) : h2 = r3;
    }
    return e3;
  }
  var yt = Pt.bind(null, true);
  var kt = Pt.bind(null, false);
  var Tt;
  !(function(t) {
    t[t.NearestLeft = -1] = "NearestLeft", t[t.None = 0] = "None", t[t.NearestRight = 1] = "NearestRight";
  })(Tt || (Tt = {}));
  var Rt = 30;
  var Dt = class {
    constructor() {
      this.Vr = [], this.Br = /* @__PURE__ */ new Map(), this.Ir = /* @__PURE__ */ new Map(), this.Er = [];
    }
    Ar() {
      return this.zr() > 0 ? this.Vr[this.Vr.length - 1] : null;
    }
    Lr() {
      return this.zr() > 0 ? this.Or(0) : null;
    }
    Ks() {
      return this.zr() > 0 ? this.Or(this.Vr.length - 1) : null;
    }
    zr() {
      return this.Vr.length;
    }
    Ki() {
      return 0 === this.zr();
    }
    Te(t) {
      return null !== this.Nr(t, 0);
    }
    kr(t) {
      return this.Fr(t);
    }
    Fr(t, i = 0) {
      const s = this.Nr(t, i);
      return null === s ? null : { ...this.Wr(s), Re: this.Or(s) };
    }
    Hr() {
      return this.Vr;
    }
    Ur(t, i, s) {
      if (this.Ki()) return null;
      let n = null;
      for (const e3 of s) {
        n = Vt(n, this.$r(t, i, e3));
      }
      return n;
    }
    ht(t) {
      this.Ir.clear(), this.Br.clear(), this.Vr = t, this.Er = t.map(((t2) => t2.Re));
    }
    qr() {
      return this.Er;
    }
    Or(t) {
      return this.Vr[t].Re;
    }
    Wr(t) {
      return this.Vr[t];
    }
    Nr(t, i) {
      const s = this.Yr(t);
      if (null === s && 0 !== i) switch (i) {
        case -1:
          return this.jr(t);
        case 1:
          return this.Kr(t);
        default:
          throw new TypeError("Unknown search mode");
      }
      return s;
    }
    jr(t) {
      let i = this.Xr(t);
      return i > 0 && (i -= 1), i !== this.Vr.length && this.Or(i) < t ? i : null;
    }
    Kr(t) {
      const i = this.Zr(t);
      return i !== this.Vr.length && t < this.Or(i) ? i : null;
    }
    Yr(t) {
      const i = this.Xr(t);
      return i === this.Vr.length || t < this.Vr[i].Re ? null : i;
    }
    Xr(t) {
      return yt(this.Vr, t, ((t2, i) => t2.Re < i));
    }
    Zr(t) {
      return kt(this.Vr, t, ((t2, i) => t2.Re > i));
    }
    Gr(t, i, s) {
      let n = null;
      for (let e3 = t; e3 < i; e3++) {
        const t2 = this.Vr[e3].Wt[s];
        Number.isNaN(t2) || (null === n ? n = { Jr: t2, Qr: t2 } : (t2 < n.Jr && (n.Jr = t2), t2 > n.Qr && (n.Qr = t2)));
      }
      return n;
    }
    $r(t, i, s) {
      if (this.Ki()) return null;
      let n = null;
      const e3 = u(this.Lr()), r2 = u(this.Ks()), h2 = Math.max(t, e3), a2 = Math.min(i, r2), l2 = Math.ceil(h2 / Rt) * Rt, o2 = Math.max(l2, Math.floor(a2 / Rt) * Rt);
      {
        const t2 = this.Xr(h2), e4 = this.Zr(Math.min(a2, l2, i));
        n = Vt(n, this.Gr(t2, e4, s));
      }
      let _2 = this.Br.get(s);
      void 0 === _2 && (_2 = /* @__PURE__ */ new Map(), this.Br.set(s, _2));
      for (let t2 = Math.max(l2 + 1, h2); t2 < o2; t2 += Rt) {
        const i2 = Math.floor(t2 / Rt);
        let e4 = _2.get(i2);
        if (void 0 === e4) {
          const t3 = this.Xr(i2 * Rt), n2 = this.Zr((i2 + 1) * Rt - 1);
          e4 = this.Gr(t3, n2, s), _2.set(i2, e4);
        }
        n = Vt(n, e4);
      }
      {
        const t2 = this.Xr(o2), i2 = this.Zr(a2);
        n = Vt(n, this.Gr(t2, i2, s));
      }
      return n;
    }
  };
  function Vt(t, i) {
    if (null === t) return i;
    if (null === i) return t;
    return { Jr: Math.min(t.Jr, i.Jr), Qr: Math.max(t.Qr, i.Qr) };
  }
  var Bt = { setLineStyle: a };
  var It = class {
    constructor(t) {
      this.th = t;
    }
    nt(t, i, s) {
      this.th.draw(t, Bt);
    }
    ih(t, i, s) {
      this.th.drawBackground?.(t, Bt);
    }
  };
  var Et = class {
    constructor(t) {
      this.Dn = null, this.sh = t;
    }
    Tt() {
      const t = this.sh.renderer();
      if (null === t) return null;
      if (this.Dn?.nh === t) return this.Dn.eh;
      const i = new It(t);
      return this.Dn = { nh: t, eh: i }, i;
    }
    rh() {
      return this.sh.zOrder?.() ?? "normal";
    }
  };
  var At = class {
    constructor(t) {
      this.hh = null, this.ah = t;
    }
    oh() {
      return this.ah;
    }
    Ns() {
      this.ah.updateAllViews?.();
    }
    Fs() {
      const t = this.ah.paneViews?.() ?? [];
      if (this.hh?.nh === t) return this.hh.eh;
      const i = t.map(((t2) => new Et(t2)));
      return this.hh = { nh: t, eh: i }, i;
    }
    jn(t, i) {
      return this.ah.hitTest?.(t, i) ?? null;
    }
  };
  var zt = class extends At {
    us() {
      return [];
    }
  };
  var Lt = class {
    constructor(t) {
      this.th = t;
    }
    nt(t, i, s) {
      this.th.draw(t, Bt);
    }
    ih(t, i, s) {
      this.th.drawBackground?.(t, Bt);
    }
  };
  var Ot = class {
    constructor(t) {
      this.Dn = null, this.sh = t;
    }
    Tt() {
      const t = this.sh.renderer();
      if (null === t) return null;
      if (this.Dn?.nh === t) return this.Dn.eh;
      const i = new Lt(t);
      return this.Dn = { nh: t, eh: i }, i;
    }
    rh() {
      return this.sh.zOrder?.() ?? "normal";
    }
  };
  function Nt(t) {
    return { ri: t.text(), Ii: t.coordinate(), Bi: t.fixedCoordinate?.(), R: t.textColor(), Z: t.backColor(), Vt: t.visible?.() ?? true, pi: t.tickVisible?.() ?? true };
  }
  var Ft = class {
    constructor(t, i) {
      this.Gt = new q(), this._h = t, this.uh = i;
    }
    Tt() {
      return this.Gt.ht({ Qi: this.uh.Qi(), ...Nt(this._h) }), this.Gt;
    }
  };
  var Wt = class extends H {
    constructor(t, i) {
      super(), this._h = t, this.Yi = i;
    }
    qi(t, i, s) {
      const n = Nt(this._h);
      s.Z = n.Z, t.R = n.R;
      const e3 = 2 / 12 * this.Yi.P();
      s.Ti = e3, s.Ri = e3, s.Ii = n.Ii, s.Bi = n.Bi, t.ri = n.ri, t.Vt = n.Vt, t.pi = n.pi;
    }
  };
  var Ht = class extends At {
    constructor(t, i) {
      super(t), this.dh = null, this.fh = null, this.ph = null, this.mh = null, this.ge = i;
    }
    cs() {
      const t = this.ah.timeAxisViews?.() ?? [];
      if (this.dh?.nh === t) return this.dh.eh;
      const i = this.ge.Qt().Et(), s = t.map(((t2) => new Ft(t2, i)));
      return this.dh = { nh: t, eh: s }, s;
    }
    Ws() {
      const t = this.ah.priceAxisViews?.() ?? [];
      if (this.fh?.nh === t) return this.fh.eh;
      const i = this.ge.Ft(), s = t.map(((t2) => new Wt(t2, i)));
      return this.fh = { nh: t, eh: s }, s;
    }
    wh() {
      const t = this.ah.priceAxisPaneViews?.() ?? [];
      if (this.ph?.nh === t) return this.ph.eh;
      const i = t.map(((t2) => new Ot(t2)));
      return this.ph = { nh: t, eh: i }, i;
    }
    gh() {
      const t = this.ah.timeAxisPaneViews?.() ?? [];
      if (this.mh?.nh === t) return this.mh.eh;
      const i = t.map(((t2) => new Ot(t2)));
      return this.mh = { nh: t, eh: i }, i;
    }
    Mh(t, i) {
      return this.ah.autoscaleInfo?.(t, i) ?? null;
    }
  };
  function Ut(t, i, s, n) {
    t.forEach(((t2) => {
      i(t2).forEach(((t3) => {
        t3.rh() === s && n.push(t3);
      }));
    }));
  }
  function $t(t) {
    return t.Fs();
  }
  function qt(t) {
    return t.wh();
  }
  function Yt(t) {
    return t.gh();
  }
  var jt = ["Area", "Line", "Baseline"];
  var Kt = class extends St {
    constructor(t, i, s, n, e3) {
      super(t), this.Yt = new Dt(), this.er = new ft(this), this.bh = [], this.Sh = new _t(this), this.xh = null, this.Ch = null, this.Ph = null, this.yh = [], this.Ps = s, this.kh = i;
      const r2 = new pt(this);
      this.vs = [r2], this.rr = new at(r2, this, t), jt.includes(this.kh) && (this.xh = new dt(this)), this.Th(), this.sh = n(this, this.Qt(), e3);
    }
    m() {
      null !== this.Ph && clearTimeout(this.Ph);
    }
    Ie(t) {
      return this.Ps.priceLineColor || t;
    }
    ye(t) {
      const i = { ke: true }, s = this.Ft();
      if (this.Qt().Et().Ki() || s.Ki() || this.Yt.Ki()) return i;
      const n = this.Qt().Et().Pe(), e3 = this.zt();
      if (null === n || null === e3) return i;
      let r2, h2;
      if (t) {
        const t2 = this.Yt.Ar();
        if (null === t2) return i;
        r2 = t2, h2 = t2.Re;
      } else {
        const t2 = this.Yt.Fr(n.bi(), -1);
        if (null === t2) return i;
        if (r2 = this.Yt.kr(t2.Re), null === r2) return i;
        h2 = t2.Re;
      }
      const a2 = r2.Wt[3], l2 = this.Rh().Dr(h2, { Wt: r2 }), o2 = s.Nt(a2, e3.Wt);
      return { ke: false, gt: a2, ri: s.Zi(a2, e3.Wt), Oe: s.Dh(a2), Ne: s.Vh(a2, e3.Wt), R: l2.cr, Ii: o2, Re: h2 };
    }
    Rh() {
      return null !== this.Ch || (this.Ch = new Ct(this)), this.Ch;
    }
    N() {
      return this.Ps;
    }
    hr(t) {
      const i = t.priceScaleId;
      void 0 !== i && i !== this.Ps.priceScaleId && this.Qt().Bh(this, i), f(this.Ps, t), void 0 !== t.priceFormat && (this.Th(), this.Qt().Ih()), this.Qt().Eh(this), this.Qt().Ah(), this.sh.yt("options");
    }
    ht(t, i) {
      this.Yt.ht(t), this.sh.yt("data"), null !== this.xh && (i && i.zh ? this.xh.be() : 0 === t.length && this.xh.Me());
      const s = this.Qt().Hn(this);
      this.Qt().Lh(s), this.Qt().Eh(this), this.Qt().Ah(), this.Qt().ar();
    }
    Oh(t) {
      const i = new bt(this, t);
      return this.bh.push(i), this.Qt().Eh(this), i;
    }
    Nh(t) {
      const i = this.bh.indexOf(t);
      -1 !== i && this.bh.splice(i, 1), this.Qt().Eh(this);
    }
    Fh() {
      return this.bh;
    }
    Rr() {
      return this.kh;
    }
    zt() {
      const t = this.Wh();
      return null === t ? null : { Wt: t.Wt[3], Hh: t.wt };
    }
    Wh() {
      const t = this.Qt().Et().Pe();
      if (null === t) return null;
      const i = t.Uh();
      return this.Yt.Fr(i, 1);
    }
    Xs() {
      return this.Yt;
    }
    $h(t) {
      const i = this.Yt.kr(t);
      return null === i ? null : "Bar" === this.kh || "Candlestick" === this.kh || "Custom" === this.kh ? { qh: i.Wt[0], Yh: i.Wt[1], jh: i.Wt[2], Kh: i.Wt[3] } : i.Wt[3];
    }
    Xh(t) {
      const i = [];
      Ut(this.yh, $t, "top", i);
      const s = this.xh;
      return null !== s && s.Vt() ? (null === this.Ph && s.xe() && (this.Ph = setTimeout((() => {
        this.Ph = null, this.Qt().Zh();
      }), 0)), s.Se(), i.unshift(s), i) : i;
    }
    Fs() {
      const t = [];
      this.Gh() || t.push(this.Sh), t.push(this.sh, this.er);
      const i = this.bh.map(((t2) => t2.lr()));
      return t.push(...i), Ut(this.yh, $t, "normal", t), t;
    }
    Jh() {
      return this.Qh($t, "bottom");
    }
    ta(t) {
      return this.Qh(qt, t);
    }
    ia(t) {
      return this.Qh(Yt, t);
    }
    sa(t, i) {
      return this.yh.map(((s) => s.jn(t, i))).filter(((t2) => null !== t2));
    }
    us() {
      return [this.rr, ...this.bh.map(((t) => t._r()))];
    }
    Ws(t, i) {
      if (i !== this.es && !this.Gh()) return [];
      const s = [...this.vs];
      for (const t2 of this.bh) s.push(t2.ur());
      return this.yh.forEach(((t2) => {
        s.push(...t2.Ws());
      })), s;
    }
    cs() {
      const t = [];
      return this.yh.forEach(((i) => {
        t.push(...i.cs());
      })), t;
    }
    Mh(t, i) {
      if (void 0 !== this.Ps.autoscaleInfoProvider) {
        const s = this.Ps.autoscaleInfoProvider((() => {
          const s2 = this.na(t, i);
          return null === s2 ? null : s2.Xe();
        }));
        return wt.Ze(s);
      }
      return this.na(t, i);
    }
    nh() {
      const t = this.Ps.priceFormat;
      return t.base ?? 1 / t.minMove;
    }
    ea() {
      return this.ra;
    }
    Ns() {
      this.sh.yt();
      for (const t of this.vs) t.yt();
      for (const t of this.bh) t.yt();
      this.er.yt(), this.Sh.yt(), this.xh?.yt(), this.yh.forEach(((t) => t.Ns()));
    }
    Ft() {
      return u(super.Ft());
    }
    At(t) {
      if (!(("Line" === this.kh || "Area" === this.kh || "Baseline" === this.kh) && this.Ps.crosshairMarkerVisible)) return null;
      const i = this.Yt.kr(t);
      if (null === i) return null;
      return { gt: i.Wt[3], ft: this.ha(), Ht: this.aa(), Ot: this.la(), Lt: this.oa(t) };
    }
    Ee() {
      return this.Ps.title;
    }
    Vt() {
      return this.Ps.visible;
    }
    _a(t) {
      this.yh.push(new Ht(t, this));
    }
    ua(t) {
      this.yh = this.yh.filter(((i) => i.oh() !== t));
    }
    ca() {
      if ("Custom" === this.kh) return (t) => this.sh.da(t);
    }
    fa() {
      if ("Custom" === this.kh) return (t) => this.sh.pa(t);
    }
    va() {
      return this.Yt.qr();
    }
    Gh() {
      return !Z(this.Ft().ma());
    }
    na(t, i) {
      if (!v(t) || !v(i) || this.Yt.Ki()) return null;
      const s = "Line" === this.kh || "Area" === this.kh || "Baseline" === this.kh || "Histogram" === this.kh ? [3] : [2, 1], n = this.Yt.Ur(t, i, s);
      let e3 = null !== n ? new mt(n.Jr, n.Qr) : null, r2 = null;
      if ("Histogram" === this.Rr()) {
        const t2 = this.Ps.base, i2 = new mt(t2, t2);
        e3 = null !== e3 ? e3.vn(i2) : i2;
      }
      return this.yh.forEach(((s2) => {
        const n2 = s2.Mh(t, i);
        if (n2?.priceRange) {
          const t2 = new mt(n2.priceRange.minValue, n2.priceRange.maxValue);
          e3 = null !== e3 ? e3.vn(t2) : t2;
        }
        n2?.margins && (r2 = n2.margins);
      })), new wt(e3, r2);
    }
    ha() {
      switch (this.kh) {
        case "Line":
        case "Area":
        case "Baseline":
          return this.Ps.crosshairMarkerRadius;
      }
      return 0;
    }
    aa() {
      switch (this.kh) {
        case "Line":
        case "Area":
        case "Baseline": {
          const t = this.Ps.crosshairMarkerBorderColor;
          if (0 !== t.length) return t;
        }
      }
      return null;
    }
    la() {
      switch (this.kh) {
        case "Line":
        case "Area":
        case "Baseline":
          return this.Ps.crosshairMarkerBorderWidth;
      }
      return 0;
    }
    oa(t) {
      switch (this.kh) {
        case "Line":
        case "Area":
        case "Baseline": {
          const t2 = this.Ps.crosshairMarkerBackgroundColor;
          if (0 !== t2.length) return t2;
        }
      }
      return this.Rh().Dr(t).cr;
    }
    Th() {
      switch (this.Ps.priceFormat.type) {
        case "custom": {
          const t = this.Ps.priceFormat.formatter;
          this.ra = { format: t, formatTickmarks: this.Ps.priceFormat.tickmarksFormatter ?? ((i) => i.map(t)) };
          break;
        }
        case "volume":
          this.ra = new nt(this.Ps.priceFormat.precision);
          break;
        case "percent":
          this.ra = new st(this.Ps.priceFormat.precision);
          break;
        default: {
          const t = Math.pow(10, this.Ps.priceFormat.precision);
          this.ra = new it(t, this.Ps.priceFormat.minMove * t);
        }
      }
      null !== this.es && this.es.wa();
    }
    Qh(t, i) {
      const s = [];
      return Ut(this.yh, t, i, s), s;
    }
  };
  var Xt = [3];
  var Zt = [0, 1, 2, 3];
  var Gt = class {
    constructor(t) {
      this.Ps = t;
    }
    ga(t, i, s) {
      let n = t;
      if (0 === this.Ps.mode) return n;
      const e3 = s.ks(), r2 = e3.zt();
      if (null === r2) return n;
      const h2 = e3.Nt(t, r2), a2 = s.Ma().filter(((t2) => t2 instanceof Kt)).reduce(((t2, n2) => {
        if (s.Un(n2) || !n2.Vt()) return t2;
        const e4 = n2.Ft(), r3 = n2.Xs();
        if (e4.Ki() || !r3.Te(i)) return t2;
        const h3 = r3.kr(i);
        if (null === h3) return t2;
        const a3 = c(n2.zt()), l3 = 3 === this.Ps.mode ? Zt : Xt;
        return t2.concat(l3.map(((t3) => e4.Nt(h3.Wt[t3], a3.Wt))));
      }), []);
      if (0 === a2.length) return n;
      a2.sort(((t2, i2) => Math.abs(t2 - h2) - Math.abs(i2 - h2)));
      const l2 = a2[0];
      return n = e3.Ts(l2, r2), n;
    }
  };
  function Jt(t, i, s) {
    return Math.min(Math.max(t, i), s);
  }
  function Qt(t, i, s) {
    return i - t <= s;
  }
  function ti(t) {
    const i = Math.ceil(t);
    return i % 2 == 0 ? i - 1 : i;
  }
  var ii = class extends R {
    constructor() {
      super(...arguments), this.Yt = null;
    }
    ht(t) {
      this.Yt = t;
    }
    et({ context: t, bitmapSize: i, horizontalPixelRatio: s, verticalPixelRatio: n }) {
      if (null === this.Yt) return;
      const e3 = Math.max(1, Math.floor(s));
      t.lineWidth = e3, (function(t2, i2) {
        t2.save(), t2.lineWidth % 2 && t2.translate(0.5, 0.5), i2(), t2.restore();
      })(t, (() => {
        const r2 = u(this.Yt);
        if (r2.ba) {
          t.strokeStyle = r2.Sa, a(t, r2.xa), t.beginPath();
          for (const n2 of r2.Ca) {
            const r3 = Math.round(n2.Pa * s);
            t.moveTo(r3, -e3), t.lineTo(r3, i.height + e3);
          }
          t.stroke();
        }
        if (r2.ya) {
          t.strokeStyle = r2.ka, a(t, r2.Ta), t.beginPath();
          for (const s2 of r2.Ra) {
            const r3 = Math.round(s2.Pa * n);
            t.moveTo(-e3, r3), t.lineTo(i.width + e3, r3);
          }
          t.stroke();
        }
      }));
    }
  };
  var si = class {
    constructor(t) {
      this.Gt = new ii(), this.xt = true, this.Pt = t;
    }
    yt() {
      this.xt = true;
    }
    Tt() {
      if (this.xt) {
        const t = this.Pt.Qt().N().grid, i = { ya: t.horzLines.visible, ba: t.vertLines.visible, ka: t.horzLines.color, Sa: t.vertLines.color, Ta: t.horzLines.style, xa: t.vertLines.style, Ra: this.Pt.ks().Da(), Ca: (this.Pt.Qt().Et().Da() || []).map(((t2) => ({ Pa: t2.coord }))) };
        this.Gt.ht(i), this.xt = false;
      }
      return this.Gt;
    }
  };
  var ni = class {
    constructor(t) {
      this.sh = new si(t);
    }
    lr() {
      return this.sh;
    }
  };
  var ei = { Va: 4, Ba: 1e-4 };
  function ri(t, i) {
    const s = 100 * (t - i) / i;
    return i < 0 ? -s : s;
  }
  function hi(t, i) {
    const s = ri(t.$e(), i), n = ri(t.qe(), i);
    return new mt(s, n);
  }
  function ai(t, i) {
    const s = 100 * (t - i) / i + 100;
    return i < 0 ? -s : s;
  }
  function li(t, i) {
    const s = ai(t.$e(), i), n = ai(t.qe(), i);
    return new mt(s, n);
  }
  function oi(t, i) {
    const s = Math.abs(t);
    if (s < 1e-15) return 0;
    const n = Math.log10(s + i.Ba) + i.Va;
    return t < 0 ? -n : n;
  }
  function _i(t, i) {
    const s = Math.abs(t);
    if (s < 1e-15) return 0;
    const n = Math.pow(10, s - i.Va) - i.Ba;
    return t < 0 ? -n : n;
  }
  function ui(t, i) {
    if (null === t) return null;
    const s = oi(t.$e(), i), n = oi(t.qe(), i);
    return new mt(s, n);
  }
  function ci(t, i) {
    if (null === t) return null;
    const s = _i(t.$e(), i), n = _i(t.qe(), i);
    return new mt(s, n);
  }
  function di(t) {
    if (null === t) return ei;
    const i = Math.abs(t.qe() - t.$e());
    if (i >= 1 || i < 1e-15) return ei;
    const s = Math.ceil(Math.abs(Math.log10(i))), n = ei.Va + s;
    return { Va: n, Ba: 1 / Math.pow(10, n) };
  }
  var fi = class {
    constructor(t, i) {
      if (this.Ia = t, this.Ea = i, (function(t2) {
        if (t2 < 0) return false;
        if (t2 > 1e18) return true;
        for (let i2 = t2; i2 > 1; i2 /= 10) if (i2 % 10 != 0) return false;
        return true;
      })(this.Ia)) this.Aa = [2, 2.5, 2];
      else {
        this.Aa = [];
        for (let t2 = this.Ia; 1 !== t2; ) {
          if (t2 % 2 == 0) this.Aa.push(2), t2 /= 2;
          else {
            if (t2 % 5 != 0) throw new Error("unexpected base");
            this.Aa.push(2, 2.5), t2 /= 5;
          }
          if (this.Aa.length > 100) throw new Error("something wrong with base");
        }
      }
    }
    za(t, i, s) {
      const n = 0 === this.Ia ? 0 : 1 / this.Ia;
      let e3 = Math.pow(10, Math.max(0, Math.ceil(Math.log10(t - i)))), r2 = 0, h2 = this.Ea[0];
      for (; ; ) {
        const t2 = Qt(e3, n, 1e-14) && e3 > n + 1e-14, i2 = Qt(e3, s * h2, 1e-14), a3 = Qt(e3, 1, 1e-14);
        if (!(t2 && i2 && a3)) break;
        e3 /= h2, h2 = this.Ea[++r2 % this.Ea.length];
      }
      if (e3 <= n + 1e-14 && (e3 = n), e3 = Math.max(1, e3), this.Aa.length > 0 && (a2 = e3, l2 = 1, o2 = 1e-14, Math.abs(a2 - l2) < o2)) for (r2 = 0, h2 = this.Aa[0]; Qt(e3, s * h2, 1e-14) && e3 > n + 1e-14; ) e3 /= h2, h2 = this.Aa[++r2 % this.Aa.length];
      var a2, l2, o2;
      return e3;
    }
  };
  var pi = class {
    constructor(t, i, s, n) {
      this.La = [], this.Yi = t, this.Ia = i, this.Oa = s, this.Na = n;
    }
    za(t, i) {
      if (t < i) throw new Error("high < low");
      const s = this.Yi.$t(), n = (t - i) * this.Fa() / s, e3 = new fi(this.Ia, [2, 2.5, 2]), r2 = new fi(this.Ia, [2, 2, 2.5]), h2 = new fi(this.Ia, [2.5, 2, 2]), a2 = [];
      return a2.push(e3.za(t, i, n), r2.za(t, i, n), h2.za(t, i, n)), (function(t2) {
        if (t2.length < 1) throw Error("array is empty");
        let i2 = t2[0];
        for (let s2 = 1; s2 < t2.length; ++s2) t2[s2] < i2 && (i2 = t2[s2]);
        return i2;
      })(a2);
    }
    Wa() {
      const t = this.Yi, i = t.zt();
      if (null === i) return void (this.La = []);
      const s = t.$t(), n = this.Oa(s - 1, i), e3 = this.Oa(0, i), r2 = this.Yi.N().entireTextOnly ? this.Ha() / 2 : 0, h2 = r2, a2 = s - 1 - r2, l2 = Math.max(n, e3), o2 = Math.min(n, e3);
      if (l2 === o2) return void (this.La = []);
      const _2 = this.za(l2, o2);
      if (this.Ua(i, _2, l2, o2, h2, a2), t.$a() && this.qa(_2, o2, l2)) {
        const t2 = this.Yi.Ya();
        this.ja(i, _2, h2, a2, t2, 2 * t2);
      }
      const u2 = this.La.map(((t2) => t2.Ka)), c2 = this.Yi.Xa(u2);
      for (let t2 = 0; t2 < this.La.length; t2++) this.La[t2].Za = c2[t2];
    }
    Da() {
      return this.La;
    }
    Ha() {
      return this.Yi.P();
    }
    Fa() {
      return Math.ceil(2.5 * this.Ha());
    }
    Ua(t, i, s, n, e3, r2) {
      const h2 = this.La, a2 = this.Yi;
      let l2 = s % i;
      l2 += l2 < 0 ? i : 0;
      const o2 = s >= n ? 1 : -1;
      let _2 = null, u2 = 0;
      for (let c2 = s - l2; c2 > n; c2 -= i) {
        const s2 = this.Na(c2, t, true);
        null !== _2 && Math.abs(s2 - _2) < this.Fa() || (s2 < e3 || s2 > r2 || (u2 < h2.length ? (h2[u2].Pa = s2, h2[u2].Za = a2.Ga(c2), h2[u2].Ka = c2) : h2.push({ Pa: s2, Za: a2.Ga(c2), Ka: c2 }), u2++, _2 = s2, a2.Ja() && (i = this.za(c2 * o2, n))));
      }
      h2.length = u2;
    }
    ja(t, i, s, n, e3, r2) {
      const h2 = this.La, a2 = this.Qa(t, s, e3, r2), l2 = this.Qa(t, n, -r2, -e3), o2 = this.Na(0, t, true) - this.Na(i, t, true);
      h2.length > 0 && h2[0].Pa - a2.Pa < o2 / 2 && h2.shift(), h2.length > 0 && l2.Pa - h2[h2.length - 1].Pa < o2 / 2 && h2.pop(), h2.unshift(a2), h2.push(l2);
    }
    Qa(t, i, s, n) {
      const e3 = (s + n) / 2, r2 = this.Oa(i + s, t), h2 = this.Oa(i + n, t), a2 = Math.min(r2, h2), l2 = Math.max(r2, h2), o2 = Math.max(0.1, this.za(l2, a2)), _2 = this.Oa(i + e3, t), u2 = _2 - _2 % o2, c2 = this.Na(u2, t, true);
      return { Za: this.Yi.Ga(u2), Pa: c2, Ka: u2 };
    }
    qa(t, i, s) {
      let n = c(this.Yi.Qe());
      return this.Yi.Ja() && (n = ci(n, this.Yi.tl())), n.$e() - i < t && s - n.qe() < t;
    }
  };
  function vi(t) {
    return t.slice().sort(((t2, i) => u(t2.hs()) - u(i.hs())));
  }
  var mi;
  !(function(t) {
    t[t.Normal = 0] = "Normal", t[t.Logarithmic = 1] = "Logarithmic", t[t.Percentage = 2] = "Percentage", t[t.IndexedTo100 = 3] = "IndexedTo100";
  })(mi || (mi = {}));
  var wi = new st();
  var gi = new it(100, 1);
  var Mi = class {
    constructor(t, i, s, n, e3) {
      this.il = 0, this.sl = null, this.Ge = null, this.nl = null, this.el = { rl: false, hl: null }, this.al = false, this.ll = 0, this.ol = 0, this._l = new d(), this.ul = new d(), this.cl = [], this.dl = null, this.fl = null, this.pl = null, this.vl = null, this.ml = null, this.ra = gi, this.wl = di(null), this.gl = t, this.Ps = i, this.Ml = s, this.bl = n, this.Sl = e3, this.xl = new pi(this, 100, this.Cl.bind(this), this.Pl.bind(this));
    }
    ma() {
      return this.gl;
    }
    N() {
      return this.Ps;
    }
    hr(t) {
      if (f(this.Ps, t), this.wa(), void 0 !== t.mode && this.yl({ ie: t.mode }), void 0 !== t.scaleMargins) {
        const i = _(t.scaleMargins.top), s = _(t.scaleMargins.bottom);
        if (i < 0 || i > 1) throw new Error(`Invalid top margin - expect value between 0 and 1, given=${i}`);
        if (s < 0 || s > 1) throw new Error(`Invalid bottom margin - expect value between 0 and 1, given=${s}`);
        if (i + s > 1) throw new Error(`Invalid margins - sum of margins must be less than 1, given=${i + s}`);
        this.kl(), this.pl = null;
      }
    }
    Tl() {
      return this.Ps.autoScale;
    }
    Rl() {
      return this.al;
    }
    Ja() {
      return 1 === this.Ps.mode;
    }
    Le() {
      return 2 === this.Ps.mode;
    }
    Dl() {
      return 3 === this.Ps.mode;
    }
    tl() {
      return this.wl;
    }
    ie() {
      return { sn: this.Ps.autoScale, Vl: this.Ps.invertScale, ie: this.Ps.mode };
    }
    yl(t) {
      const i = this.ie();
      let s = null;
      void 0 !== t.sn && (this.Ps.autoScale = t.sn), void 0 !== t.ie && (this.Ps.mode = t.ie, 2 !== t.ie && 3 !== t.ie || (this.Ps.autoScale = true), this.el.rl = false), 1 === i.ie && t.ie !== i.ie && (!(function(t2, i2) {
        if (null === t2) return false;
        const s2 = _i(t2.$e(), i2), n2 = _i(t2.qe(), i2);
        return isFinite(s2) && isFinite(n2);
      })(this.Ge, this.wl) ? this.Ps.autoScale = true : (s = ci(this.Ge, this.wl), null !== s && this.Bl(s))), 1 === t.ie && t.ie !== i.ie && (s = ui(this.Ge, this.wl), null !== s && this.Bl(s));
      const n = i.ie !== this.Ps.mode;
      n && (2 === i.ie || this.Le()) && this.wa(), n && (3 === i.ie || this.Dl()) && this.wa(), void 0 !== t.Vl && i.Vl !== t.Vl && (this.Ps.invertScale = t.Vl, this.Il()), this.ul.p(i, this.ie());
    }
    El() {
      return this.ul;
    }
    P() {
      return this.Ml.fontSize;
    }
    $t() {
      return this.il;
    }
    Al(t) {
      this.il !== t && (this.il = t, this.kl(), this.pl = null);
    }
    zl() {
      if (this.sl) return this.sl;
      const t = this.$t() - this.Ll() - this.Ol();
      return this.sl = t, t;
    }
    Qe() {
      return this.Nl(), this.Ge;
    }
    Bl(t, i) {
      const s = this.Ge;
      (i || null === s && null !== t || null !== s && !s.He(t)) && (this.pl = null, this.Ge = t);
    }
    Fl(t) {
      this.Bl(t), this.Wl(null !== t);
    }
    Ki() {
      return this.Nl(), 0 === this.il || !this.Ge || this.Ge.Ki();
    }
    Hl(t) {
      return this.Vl() ? t : this.$t() - 1 - t;
    }
    Nt(t, i) {
      return this.Le() ? t = ri(t, i) : this.Dl() && (t = ai(t, i)), this.Pl(t, i);
    }
    Ul(t, i, s) {
      this.Nl();
      const n = this.Ol(), e3 = u(this.Qe()), r2 = e3.$e(), h2 = e3.qe(), a2 = this.zl() - 1, l2 = this.Vl(), o2 = a2 / (h2 - r2), _2 = void 0 === s ? 0 : s.from, c2 = void 0 === s ? t.length : s.to, d2 = this.$l();
      for (let s2 = _2; s2 < c2; s2++) {
        const e4 = t[s2], h3 = e4.gt;
        if (isNaN(h3)) continue;
        let a3 = h3;
        null !== d2 && (a3 = d2(e4.gt, i));
        const _3 = n + o2 * (a3 - r2), u2 = l2 ? _3 : this.il - 1 - _3;
        e4.ut = u2;
      }
    }
    ql(t, i, s) {
      this.Nl();
      const n = this.Ol(), e3 = u(this.Qe()), r2 = e3.$e(), h2 = e3.qe(), a2 = this.zl() - 1, l2 = this.Vl(), o2 = a2 / (h2 - r2), _2 = void 0 === s ? 0 : s.from, c2 = void 0 === s ? t.length : s.to, d2 = this.$l();
      for (let s2 = _2; s2 < c2; s2++) {
        const e4 = t[s2];
        let h3 = e4.qh, a3 = e4.Yh, _3 = e4.jh, u2 = e4.Kh;
        null !== d2 && (h3 = d2(e4.qh, i), a3 = d2(e4.Yh, i), _3 = d2(e4.jh, i), u2 = d2(e4.Kh, i));
        let c3 = n + o2 * (h3 - r2), f2 = l2 ? c3 : this.il - 1 - c3;
        e4.Yl = f2, c3 = n + o2 * (a3 - r2), f2 = l2 ? c3 : this.il - 1 - c3, e4.jl = f2, c3 = n + o2 * (_3 - r2), f2 = l2 ? c3 : this.il - 1 - c3, e4.Kl = f2, c3 = n + o2 * (u2 - r2), f2 = l2 ? c3 : this.il - 1 - c3, e4.Xl = f2;
      }
    }
    Ts(t, i) {
      const s = this.Cl(t, i);
      return this.Zl(s, i);
    }
    Zl(t, i) {
      let s = t;
      return this.Le() ? s = (function(t2, i2) {
        return i2 < 0 && (t2 = -t2), t2 / 100 * i2 + i2;
      })(s, i) : this.Dl() && (s = (function(t2, i2) {
        return t2 -= 100, i2 < 0 && (t2 = -t2), t2 / 100 * i2 + i2;
      })(s, i)), s;
    }
    Ma() {
      return this.cl;
    }
    Dt() {
      return this.fl || (this.fl = vi(this.cl)), this.fl;
    }
    Gl(t) {
      -1 === this.cl.indexOf(t) && (this.cl.push(t), this.wa(), this.Jl());
    }
    Ql(t) {
      const i = this.cl.indexOf(t);
      if (-1 === i) throw new Error("source is not attached to scale");
      this.cl.splice(i, 1), 0 === this.cl.length && (this.yl({ sn: true }), this.Bl(null)), this.wa(), this.Jl();
    }
    zt() {
      let t = null;
      for (const i of this.cl) {
        const s = i.zt();
        null !== s && ((null === t || s.Hh < t.Hh) && (t = s));
      }
      return null === t ? null : t.Wt;
    }
    Vl() {
      return this.Ps.invertScale;
    }
    Da() {
      const t = null === this.zt();
      if (null !== this.pl && (t || this.pl.io === t)) return this.pl.Da;
      this.xl.Wa();
      const i = this.xl.Da();
      return this.pl = { Da: i, io: t }, this._l.p(), i;
    }
    so() {
      return this._l;
    }
    no(t) {
      this.Le() || this.Dl() || null === this.vl && null === this.nl && (this.Ki() || (this.vl = this.il - t, this.nl = u(this.Qe()).Ue()));
    }
    eo(t) {
      if (this.Le() || this.Dl()) return;
      if (null === this.vl) return;
      this.yl({ sn: false }), (t = this.il - t) < 0 && (t = 0);
      let i = (this.vl + 0.2 * (this.il - 1)) / (t + 0.2 * (this.il - 1));
      const s = u(this.nl).Ue();
      i = Math.max(i, 0.1), s.je(i), this.Bl(s);
    }
    ro() {
      this.Le() || this.Dl() || (this.vl = null, this.nl = null);
    }
    ho(t) {
      this.Tl() || null === this.ml && null === this.nl && (this.Ki() || (this.ml = t, this.nl = u(this.Qe()).Ue()));
    }
    ao(t) {
      if (this.Tl()) return;
      if (null === this.ml) return;
      const i = u(this.Qe()).Ye() / (this.zl() - 1);
      let s = t - this.ml;
      this.Vl() && (s *= -1);
      const n = s * i, e3 = u(this.nl).Ue();
      e3.Ke(n), this.Bl(e3, true), this.pl = null;
    }
    lo() {
      this.Tl() || null !== this.ml && (this.ml = null, this.nl = null);
    }
    ea() {
      return this.ra || this.wa(), this.ra;
    }
    Zi(t, i) {
      switch (this.Ps.mode) {
        case 2:
          return this.oo(ri(t, i));
        case 3:
          return this.ea().format(ai(t, i));
        default:
          return this.nr(t);
      }
    }
    Ga(t) {
      switch (this.Ps.mode) {
        case 2:
          return this.oo(t);
        case 3:
          return this.ea().format(t);
        default:
          return this.nr(t);
      }
    }
    Xa(t) {
      switch (this.Ps.mode) {
        case 2:
          return this._o(t);
        case 3:
          return this.ea().formatTickmarks(t);
        default:
          return this.uo(t);
      }
    }
    Dh(t) {
      return this.nr(t, u(this.dl).ea());
    }
    Vh(t, i) {
      return t = ri(t, i), this.oo(t, wi);
    }
    co() {
      return this.cl;
    }
    do(t) {
      this.el = { hl: t, rl: false };
    }
    Ns() {
      this.cl.forEach(((t) => t.Ns()));
    }
    $a() {
      return this.Ps.ensureEdgeTickMarksVisible && this.Tl();
    }
    Ya() {
      return this.P() / 2;
    }
    wa() {
      this.pl = null;
      let t = 1 / 0;
      this.dl = null;
      for (const i2 of this.cl) i2.hs() < t && (t = i2.hs(), this.dl = i2);
      let i = 100;
      null !== this.dl && (i = Math.round(this.dl.nh())), this.ra = gi, this.Le() ? (this.ra = wi, i = 100) : this.Dl() ? (this.ra = new it(100, 1), i = 100) : null !== this.dl && (this.ra = this.dl.ea()), this.xl = new pi(this, i, this.Cl.bind(this), this.Pl.bind(this)), this.xl.Wa();
    }
    Jl() {
      this.fl = null;
    }
    fo() {
      return null === this.dl || this.Le() || this.Dl() ? 1 : 1 / this.dl.nh();
    }
    Xi() {
      return this.Sl;
    }
    Wl(t) {
      this.al = t;
    }
    Ll() {
      return this.Vl() ? this.Ps.scaleMargins.bottom * this.$t() + this.ol : this.Ps.scaleMargins.top * this.$t() + this.ll;
    }
    Ol() {
      return this.Vl() ? this.Ps.scaleMargins.top * this.$t() + this.ll : this.Ps.scaleMargins.bottom * this.$t() + this.ol;
    }
    Nl() {
      this.el.rl || (this.el.rl = true, this.po());
    }
    kl() {
      this.sl = null;
    }
    Pl(t, i) {
      if (this.Nl(), this.Ki()) return 0;
      t = this.Ja() && t ? oi(t, this.wl) : t;
      const s = u(this.Qe()), n = this.Ol() + (this.zl() - 1) * (t - s.$e()) / s.Ye();
      return this.Hl(n);
    }
    Cl(t, i) {
      if (this.Nl(), this.Ki()) return 0;
      const s = this.Hl(t), n = u(this.Qe()), e3 = n.$e() + n.Ye() * ((s - this.Ol()) / (this.zl() - 1));
      return this.Ja() ? _i(e3, this.wl) : e3;
    }
    Il() {
      this.pl = null, this.xl.Wa();
    }
    po() {
      if (this.Rl() && !this.Tl()) return;
      const t = this.el.hl;
      if (null === t) return;
      let i = null;
      const s = this.co();
      let n = 0, e3 = 0;
      for (const r3 of s) {
        if (!r3.Vt()) continue;
        const s2 = r3.zt();
        if (null === s2) continue;
        const h3 = r3.Mh(t.Uh(), t.bi());
        let a2 = h3 && h3.Qe();
        if (null !== a2) {
          switch (this.Ps.mode) {
            case 1:
              a2 = ui(a2, this.wl);
              break;
            case 2:
              a2 = hi(a2, s2.Wt);
              break;
            case 3:
              a2 = li(a2, s2.Wt);
          }
          if (i = null === i ? a2 : i.vn(u(a2)), null !== h3) {
            const t2 = h3.tr();
            null !== t2 && (n = Math.max(n, t2.above), e3 = Math.max(e3, t2.below));
          }
        }
      }
      if (this.$a() && (n = Math.max(n, this.Ya()), e3 = Math.max(e3, this.Ya())), n === this.ll && e3 === this.ol || (this.ll = n, this.ol = e3, this.pl = null, this.kl()), null !== i) {
        if (i.$e() === i.qe()) {
          const t2 = 5 * this.fo();
          this.Ja() && (i = ci(i, this.wl)), i = new mt(i.$e() - t2, i.qe() + t2), this.Ja() && (i = ui(i, this.wl));
        }
        if (this.Ja()) {
          const t2 = ci(i, this.wl), s2 = di(t2);
          if (r2 = s2, h2 = this.wl, r2.Va !== h2.Va || r2.Ba !== h2.Ba) {
            const n2 = null !== this.nl ? ci(this.nl, this.wl) : null;
            this.wl = s2, i = ui(t2, s2), null !== n2 && (this.nl = ui(n2, s2));
          }
        }
        this.Bl(i);
      } else null === this.Ge && (this.Bl(new mt(-0.5, 0.5)), this.wl = di(null));
      var r2, h2;
    }
    $l() {
      return this.Le() ? ri : this.Dl() ? ai : this.Ja() ? (t) => oi(t, this.wl) : null;
    }
    vo(t, i, s) {
      return void 0 === i ? (void 0 === s && (s = this.ea()), s.format(t)) : i(t);
    }
    mo(t, i, s) {
      return void 0 === i ? (void 0 === s && (s = this.ea()), s.formatTickmarks(t)) : i(t);
    }
    nr(t, i) {
      return this.vo(t, this.bl.priceFormatter, i);
    }
    uo(t, i) {
      const s = this.bl.priceFormatter;
      return this.mo(t, this.bl.tickmarksPriceFormatter ?? (s ? (t2) => t2.map(s) : void 0), i);
    }
    oo(t, i) {
      return this.vo(t, this.bl.percentageFormatter, i);
    }
    _o(t, i) {
      const s = this.bl.percentageFormatter;
      return this.mo(t, this.bl.tickmarksPercentageFormatter ?? (s ? (t2) => t2.map(s) : void 0), i);
    }
  };
  function bi(t) {
    return t instanceof Kt;
  }
  var Si = class {
    constructor(t, i) {
      this.cl = [], this.wo = /* @__PURE__ */ new Map(), this.il = 0, this.Mo = 0, this.bo = 1, this.fl = null, this.So = false, this.xo = new d(), this.yh = [], this.uh = t, this.ts = i, this.Co = new ni(this);
      const s = i.N();
      this.Po = this.yo("left", s.leftPriceScale), this.ko = this.yo("right", s.rightPriceScale), this.Po.El().i(this.To.bind(this, this.Po), this), this.ko.El().i(this.To.bind(this, this.ko), this), this.Ro(s);
    }
    Ro(t) {
      if (t.leftPriceScale && this.Po.hr(t.leftPriceScale), t.rightPriceScale && this.ko.hr(t.rightPriceScale), t.localization && (this.Po.wa(), this.ko.wa()), t.overlayPriceScales) {
        const i = Array.from(this.wo.values());
        for (const s of i) {
          const i2 = u(s[0].Ft());
          i2.hr(t.overlayPriceScales), t.localization && i2.wa();
        }
      }
    }
    Do(t) {
      switch (t) {
        case "left":
          return this.Po;
        case "right":
          return this.ko;
      }
      return this.wo.has(t) ? _(this.wo.get(t))[0].Ft() : null;
    }
    m() {
      this.Qt().Vo().u(this), this.Po.El().u(this), this.ko.El().u(this), this.cl.forEach(((t) => {
        t.m && t.m();
      })), this.yh = this.yh.filter(((t) => {
        const i = t.oh();
        return i.detached && i.detached(), false;
      })), this.xo.p();
    }
    Bo() {
      return this.bo;
    }
    Io(t) {
      this.bo = t;
    }
    Qt() {
      return this.ts;
    }
    Qi() {
      return this.Mo;
    }
    $t() {
      return this.il;
    }
    Eo(t) {
      this.Mo = t, this.Ao();
    }
    Al(t) {
      this.il = t, this.Po.Al(t), this.ko.Al(t), this.cl.forEach(((i) => {
        if (this.Un(i)) {
          const s = i.Ft();
          null !== s && s.Al(t);
        }
      })), this.Ao();
    }
    zo(t) {
      this.So = t;
    }
    Lo() {
      return this.So;
    }
    Oo() {
      return this.cl.filter(bi);
    }
    Ma() {
      return this.cl;
    }
    Un(t) {
      const i = t.Ft();
      return null === i || this.Po !== i && this.ko !== i;
    }
    Gl(t, i, s) {
      this.No(t, i, s ? t.hs() : this.cl.length);
    }
    Ql(t, i) {
      const s = this.cl.indexOf(t);
      o(-1 !== s, "removeDataSource: invalid data source"), this.cl.splice(s, 1), i || this.cl.forEach(((t2, i2) => t2.ls(i2)));
      const n = u(t.Ft()).ma();
      if (this.wo.has(n)) {
        const i2 = _(this.wo.get(n)), s2 = i2.indexOf(t);
        -1 !== s2 && (i2.splice(s2, 1), 0 === i2.length && this.wo.delete(n));
      }
      const e3 = t.Ft();
      e3 && e3.Ma().indexOf(t) >= 0 && (e3.Ql(t), this.Fo(e3)), this.fl = null;
    }
    qn(t) {
      return t === this.Po ? "left" : t === this.ko ? "right" : "overlay";
    }
    Wo() {
      return this.Po;
    }
    Ho() {
      return this.ko;
    }
    Uo(t, i) {
      t.no(i);
    }
    $o(t, i) {
      t.eo(i), this.Ao();
    }
    qo(t) {
      t.ro();
    }
    Yo(t, i) {
      t.ho(i);
    }
    jo(t, i) {
      t.ao(i), this.Ao();
    }
    Ko(t) {
      t.lo();
    }
    Ao() {
      this.cl.forEach(((t) => {
        t.Ns();
      }));
    }
    ks() {
      let t = null;
      return this.ts.N().rightPriceScale.visible && 0 !== this.ko.Ma().length ? t = this.ko : this.ts.N().leftPriceScale.visible && 0 !== this.Po.Ma().length ? t = this.Po : 0 !== this.cl.length && (t = this.cl[0].Ft()), null === t && (t = this.ko), t;
    }
    $n() {
      let t = null;
      return this.ts.N().rightPriceScale.visible ? t = this.ko : this.ts.N().leftPriceScale.visible && (t = this.Po), t;
    }
    Fo(t) {
      null !== t && t.Tl() && this.Xo(t);
    }
    Zo(t) {
      const i = this.uh.Pe();
      t.yl({ sn: true }), null !== i && t.do(i), this.Ao();
    }
    Go() {
      this.Xo(this.Po), this.Xo(this.ko);
    }
    Jo() {
      this.Fo(this.Po), this.Fo(this.ko), this.cl.forEach(((t) => {
        this.Un(t) && this.Fo(t.Ft());
      })), this.Ao(), this.ts.ar();
    }
    Dt() {
      return null === this.fl && (this.fl = vi(this.cl)), this.fl;
    }
    Qo(t, i) {
      i = Jt(i, 0, this.cl.length - 1);
      const s = this.cl.indexOf(t);
      o(-1 !== s, "setSeriesOrder: invalid data source"), this.cl.splice(s, 1), this.cl.splice(i, 0, t), this.cl.forEach(((t2, i2) => t2.ls(i2))), this.fl = null;
      for (const t2 of [this.Po, this.ko]) t2.Jl(), t2.wa();
      this.ts.ar();
    }
    Bt() {
      return this.Dt().filter(bi);
    }
    t_() {
      return this.xo;
    }
    i_() {
      return this.Co;
    }
    _a(t) {
      this.yh.push(new zt(t));
    }
    ua(t) {
      this.yh = this.yh.filter(((i) => i.oh() !== t)), t.detached && t.detached(), this.ts.ar();
    }
    s_() {
      return this.yh;
    }
    sa(t, i) {
      return this.yh.map(((s) => s.jn(t, i))).filter(((t2) => null !== t2));
    }
    Xo(t) {
      const i = t.co();
      if (i && i.length > 0 && !this.uh.Ki()) {
        const i2 = this.uh.Pe();
        null !== i2 && t.do(i2);
      }
      t.Ns();
    }
    No(t, i, s) {
      let n = this.Do(i);
      if (null === n && (n = this.yo(i, this.ts.N().overlayPriceScales)), this.cl.splice(s, 0, t), !Z(i)) {
        const s2 = this.wo.get(i) || [];
        s2.push(t), this.wo.set(i, s2);
      }
      t.ls(s), n.Gl(t), t._s(n), this.Fo(n), this.fl = null;
    }
    To(t, i, s) {
      i.ie !== s.ie && this.Xo(t);
    }
    yo(t, i) {
      const s = { visible: true, autoScale: true, ...g(i) }, n = new Mi(t, s, this.ts.N().layout, this.ts.N().localization, this.ts.Xi());
      return n.Al(this.$t()), n;
    }
  };
  function xi(t) {
    return { n_: t.n_, e_: { Kn: t.r_.externalId }, h_: t.r_.cursorStyle };
  }
  function Ci(t, i, s, n) {
    for (const e3 of t) {
      const t2 = e3.Tt(n);
      if (null !== t2 && t2.jn) {
        const n2 = t2.jn(i, s);
        if (null !== n2) return { a_: e3, e_: n2 };
      }
    }
    return null;
  }
  function Pi(t) {
    return void 0 !== t.Fs;
  }
  function yi(t, i, s) {
    const n = [t, ...t.Dt()], e3 = (function(t2, i2, s2) {
      let n2, e4;
      for (const a2 of t2) {
        const t3 = a2.sa?.(i2, s2) ?? [];
        for (const i3 of t3) r2 = i3.zOrder, h2 = n2?.zOrder, (!h2 || "top" === r2 && "top" !== h2 || "normal" === r2 && "bottom" === h2) && (n2 = i3, e4 = a2);
      }
      var r2, h2;
      return n2 && e4 ? { r_: n2, n_: e4 } : null;
    })(n, i, s);
    if ("top" === e3?.r_.zOrder) return xi(e3);
    for (const r2 of n) {
      if (e3 && e3.n_ === r2 && "bottom" !== e3.r_.zOrder && !e3.r_.isBackground) return xi(e3);
      if (Pi(r2)) {
        const n2 = Ci(r2.Fs(t), i, s, t);
        if (null !== n2) return { n_: r2, a_: n2.a_, e_: n2.e_ };
      }
      if (e3 && e3.n_ === r2 && "bottom" !== e3.r_.zOrder && e3.r_.isBackground) return xi(e3);
    }
    return e3?.r_ ? xi(e3) : null;
  }
  var ki = class {
    constructor(t, i, s = 50) {
      this.yn = 0, this.kn = 1, this.Tn = 1, this.Dn = /* @__PURE__ */ new Map(), this.Rn = /* @__PURE__ */ new Map(), this.l_ = t, this.o_ = i, this.Vn = s;
    }
    __(t) {
      const i = t.time, s = this.o_.cacheKey(i), n = this.Dn.get(s);
      if (void 0 !== n) return n.u_;
      if (this.yn === this.Vn) {
        const t2 = this.Rn.get(this.Tn);
        this.Rn.delete(this.Tn), this.Dn.delete(_(t2)), this.Tn++, this.yn--;
      }
      const e3 = this.l_(t);
      return this.Dn.set(s, { u_: e3, An: this.kn }), this.Rn.set(this.kn, s), this.yn++, this.kn++, e3;
    }
  };
  var Ti = class {
    constructor(t, i) {
      o(t <= i, "right should be >= left"), this.c_ = t, this.d_ = i;
    }
    Uh() {
      return this.c_;
    }
    bi() {
      return this.d_;
    }
    f_() {
      return this.d_ - this.c_ + 1;
    }
    Te(t) {
      return this.c_ <= t && t <= this.d_;
    }
    He(t) {
      return this.c_ === t.Uh() && this.d_ === t.bi();
    }
  };
  function Ri(t, i) {
    return null === t || null === i ? t === i : t.He(i);
  }
  var Di = class {
    constructor() {
      this.p_ = /* @__PURE__ */ new Map(), this.Dn = null, this.v_ = false;
    }
    m_(t) {
      this.v_ = t, this.Dn = null;
    }
    w_(t, i) {
      this.g_(i), this.Dn = null;
      for (let s = i; s < t.length; ++s) {
        const i2 = t[s];
        let n = this.p_.get(i2.timeWeight);
        void 0 === n && (n = [], this.p_.set(i2.timeWeight, n)), n.push({ index: s, time: i2.time, weight: i2.timeWeight, originalTime: i2.originalTime });
      }
    }
    M_(t, i, s, n, e3) {
      const r2 = Math.ceil(i / t);
      return null !== this.Dn && this.Dn.b_ === r2 && e3 === this.Dn.S_ && s === this.Dn.x_ || (this.Dn = { S_: e3, x_: s, Da: this.C_(r2, s, n), b_: r2 }), this.Dn.Da;
    }
    g_(t) {
      if (0 === t) return void this.p_.clear();
      const i = [];
      this.p_.forEach(((s, n) => {
        t <= s[0].index ? i.push(n) : s.splice(yt(s, t, ((i2) => i2.index < t)), 1 / 0);
      }));
      for (const t2 of i) this.p_.delete(t2);
    }
    C_(t, i, s) {
      let n = [];
      const e3 = (t2) => !i || s.has(t2.index);
      for (const i2 of Array.from(this.p_.keys()).sort(((t2, i3) => i3 - t2))) {
        if (!this.p_.get(i2)) continue;
        const s2 = n;
        n = [];
        const r2 = s2.length;
        let h2 = 0;
        const a2 = _(this.p_.get(i2)), l2 = a2.length;
        let o2 = 1 / 0, u2 = -1 / 0;
        for (let i3 = 0; i3 < l2; i3++) {
          const l3 = a2[i3], _2 = l3.index;
          for (; h2 < r2; ) {
            const t2 = s2[h2], i4 = t2.index;
            if (!(i4 < _2 && e3(t2))) {
              o2 = i4;
              break;
            }
            h2++, n.push(t2), u2 = i4, o2 = 1 / 0;
          }
          if (o2 - _2 >= t && _2 - u2 >= t && e3(l3)) n.push(l3), u2 = _2;
          else if (this.v_) return s2;
        }
        for (; h2 < r2; h2++) e3(s2[h2]) && n.push(s2[h2]);
      }
      return n;
    }
  };
  var Vi = class _Vi {
    constructor(t) {
      this.P_ = t;
    }
    y_() {
      return null === this.P_ ? null : new Ti(Math.floor(this.P_.Uh()), Math.ceil(this.P_.bi()));
    }
    k_() {
      return this.P_;
    }
    static T_() {
      return new _Vi(null);
    }
  };
  function Bi(t, i) {
    return t.weight > i.weight ? t : i;
  }
  var Ii = class {
    constructor(t, i, s, n) {
      this.Mo = 0, this.R_ = null, this.D_ = [], this.ml = null, this.vl = null, this.V_ = new Di(), this.B_ = /* @__PURE__ */ new Map(), this.I_ = Vi.T_(), this.E_ = true, this.A_ = new d(), this.z_ = new d(), this.L_ = new d(), this.O_ = null, this.N_ = null, this.F_ = /* @__PURE__ */ new Map(), this.W_ = -1, this.H_ = [], this.Ps = i, this.bl = s, this.U_ = i.rightOffset, this.q_ = i.barSpacing, this.ts = t, this.Y_(i), this.o_ = n, this.j_(), this.V_.m_(i.uniformDistribution), this.K_();
    }
    N() {
      return this.Ps;
    }
    X_(t) {
      f(this.bl, t), this.Z_(), this.j_();
    }
    hr(t, i) {
      f(this.Ps, t), this.Ps.fixLeftEdge && this.G_(), this.Ps.fixRightEdge && this.J_(), void 0 !== t.barSpacing && this.ts.dn(t.barSpacing), void 0 !== t.rightOffset && this.ts.fn(t.rightOffset), this.Y_(t), void 0 === t.minBarSpacing && void 0 === t.maxBarSpacing || this.ts.dn(t.barSpacing ?? this.q_), void 0 !== t.ignoreWhitespaceIndices && t.ignoreWhitespaceIndices !== this.Ps.ignoreWhitespaceIndices && this.K_(), this.Z_(), this.j_(), this.L_.p();
    }
    Rs(t) {
      return this.D_[t]?.time ?? null;
    }
    ss(t) {
      return this.D_[t] ?? null;
    }
    Q_(t, i) {
      if (this.D_.length < 1) return null;
      if (this.o_.key(t) > this.o_.key(this.D_[this.D_.length - 1].time)) return i ? this.D_.length - 1 : null;
      const s = yt(this.D_, this.o_.key(t), ((t2, i2) => this.o_.key(t2.time) < i2));
      return this.o_.key(t) < this.o_.key(this.D_[s].time) ? i ? s : null : s;
    }
    Ki() {
      return 0 === this.Mo || 0 === this.D_.length || null === this.R_;
    }
    tu() {
      return this.D_.length > 0;
    }
    Pe() {
      return this.iu(), this.I_.y_();
    }
    su() {
      return this.iu(), this.I_.k_();
    }
    nu() {
      const t = this.Pe();
      if (null === t) return null;
      const i = { from: t.Uh(), to: t.bi() };
      return this.eu(i);
    }
    eu(t) {
      const i = Math.round(t.from), s = Math.round(t.to), n = u(this.ru()), e3 = u(this.hu());
      return { from: u(this.ss(Math.max(n, i))), to: u(this.ss(Math.min(e3, s))) };
    }
    au(t) {
      return { from: u(this.Q_(t.from, true)), to: u(this.Q_(t.to, true)) };
    }
    Qi() {
      return this.Mo;
    }
    Eo(t) {
      if (!isFinite(t) || t <= 0) return;
      if (this.Mo === t) return;
      const i = this.su(), s = this.Mo;
      if (this.Mo = t, this.E_ = true, this.Ps.lockVisibleTimeRangeOnResize && 0 !== s) {
        const i2 = this.q_ * t / s;
        this.q_ = i2;
      }
      if (this.Ps.fixLeftEdge && null !== i && i.Uh() <= 0) {
        const i2 = s - t;
        this.U_ -= Math.round(i2 / this.q_) + 1, this.E_ = true;
      }
      this.lu(), this.ou();
    }
    qt(t) {
      if (this.Ki() || !v(t)) return 0;
      const i = this._u() + this.U_ - t;
      return this.Mo - (i + 0.5) * this.q_ - 1;
    }
    uu(t, i) {
      const s = this._u(), n = void 0 === i ? 0 : i.from, e3 = void 0 === i ? t.length : i.to;
      for (let i2 = n; i2 < e3; i2++) {
        const n2 = t[i2].wt, e4 = s + this.U_ - n2, r2 = this.Mo - (e4 + 0.5) * this.q_ - 1;
        t[i2]._t = r2;
      }
    }
    cu(t, i) {
      const s = Math.ceil(this.du(t));
      return i && this.Ps.ignoreWhitespaceIndices && !this.fu(s) ? this.pu(s) : s;
    }
    fn(t) {
      this.E_ = true, this.U_ = t, this.ou(), this.ts.vu(), this.ts.ar();
    }
    mu() {
      return this.q_;
    }
    dn(t) {
      const i = this.q_;
      if (this.wu(t), void 0 !== this.Ps.rightOffsetPixels && 0 !== i) {
        const t2 = this.U_ * i / this.q_;
        this.U_ = t2;
      }
      this.ou(), this.ts.vu(), this.ts.ar();
    }
    gu() {
      return this.U_;
    }
    Da() {
      if (this.Ki()) return null;
      if (null !== this.N_) return this.N_;
      const t = this.q_, i = 5 * (this.ts.N().layout.fontSize + 4) / 8 * (this.Ps.tickMarkMaxCharacterLength || 8), s = Math.round(i / t), n = u(this.Pe()), e3 = Math.max(n.Uh(), n.Uh() - s), r2 = Math.max(n.bi(), n.bi() - s), h2 = this.V_.M_(t, i, this.Ps.ignoreWhitespaceIndices, this.F_, this.W_), a2 = this.ru() + s, l2 = this.hu() - s, o2 = this.Mu(), _2 = this.Ps.fixLeftEdge || o2, c2 = this.Ps.fixRightEdge || o2;
      let d2 = 0;
      for (const t2 of h2) {
        if (!(e3 <= t2.index && t2.index <= r2)) continue;
        let s2;
        d2 < this.H_.length ? (s2 = this.H_[d2], s2.coord = this.qt(t2.index), s2.label = this.bu(t2), s2.weight = t2.weight) : (s2 = { needAlignCoordinate: false, coord: this.qt(t2.index), label: this.bu(t2), weight: t2.weight }, this.H_.push(s2)), this.q_ > i / 2 && !o2 ? s2.needAlignCoordinate = false : s2.needAlignCoordinate = _2 && t2.index <= a2 || c2 && t2.index >= l2, d2++;
      }
      return this.H_.length = d2, this.N_ = this.H_, this.H_;
    }
    Su() {
      let t;
      this.E_ = true, this.dn(this.Ps.barSpacing), t = void 0 !== this.Ps.rightOffsetPixels ? this.Ps.rightOffsetPixels / this.mu() : this.Ps.rightOffset, this.fn(t);
    }
    xu(t) {
      this.E_ = true, this.R_ = t, this.ou(), this.G_();
    }
    Cu(t, i) {
      const s = this.du(t), n = this.mu(), e3 = n + i * (n / 10);
      this.dn(e3), this.Ps.rightBarStaysOnScroll || this.fn(this.gu() + (s - this.du(t)));
    }
    no(t) {
      this.ml && this.lo(), null === this.vl && null === this.O_ && (this.Ki() || (this.vl = t, this.Pu()));
    }
    eo(t) {
      if (null === this.O_) return;
      const i = Jt(this.Mo - t, 0, this.Mo), s = Jt(this.Mo - u(this.vl), 0, this.Mo);
      0 !== i && 0 !== s && this.dn(this.O_.mu * i / s);
    }
    ro() {
      null !== this.vl && (this.vl = null, this.yu());
    }
    ho(t) {
      null === this.ml && null === this.O_ && (this.Ki() || (this.ml = t, this.Pu()));
    }
    ao(t) {
      if (null === this.ml) return;
      const i = (this.ml - t) / this.mu();
      this.U_ = u(this.O_).gu + i, this.E_ = true, this.ou();
    }
    lo() {
      null !== this.ml && (this.ml = null, this.yu());
    }
    ku() {
      this.Tu(this.Ps.rightOffset);
    }
    Tu(t, i = 400) {
      if (!isFinite(t)) throw new RangeError("offset is required and must be finite number");
      if (!isFinite(i) || i <= 0) throw new RangeError("animationDuration (optional) must be finite positive number");
      const s = this.U_, n = performance.now();
      this.ts._n({ Ru: (t2) => (t2 - n) / i >= 1, Du: (e3) => {
        const r2 = (e3 - n) / i;
        return r2 >= 1 ? t : s + (t - s) * r2;
      } });
    }
    yt(t, i) {
      this.E_ = true, this.D_ = t, this.V_.w_(t, i), this.ou();
    }
    Vu() {
      return this.A_;
    }
    Bu() {
      return this.z_;
    }
    Iu() {
      return this.L_;
    }
    _u() {
      return this.R_ || 0;
    }
    Eu(t, i) {
      const s = t.f_(), n = i && this.Ps.rightOffsetPixels || 0;
      this.wu((this.Mo - n) / s), this.U_ = t.bi() - this._u(), i && (this.U_ = n ? n / this.mu() : this.Ps.rightOffset), this.ou(), this.E_ = true, this.ts.vu(), this.ts.ar();
    }
    Au() {
      const t = this.ru(), i = this.hu();
      null !== t && null !== i && this.Eu(new Ti(t, i), true);
    }
    zu(t) {
      const i = new Ti(t.from, t.to);
      this.Eu(i);
    }
    ns(t) {
      return void 0 !== this.bl.timeFormatter ? this.bl.timeFormatter(t.originalTime) : this.o_.formatHorzItem(t.time);
    }
    K_() {
      if (!this.Ps.ignoreWhitespaceIndices) return;
      this.F_.clear();
      const t = this.ts.js();
      for (const i of t) for (const t2 of i.va()) this.F_.set(t2, true);
      this.W_++;
    }
    Mu() {
      const t = this.ts.N().handleScroll, i = this.ts.N().handleScale;
      return !(t.horzTouchDrag || t.mouseWheel || t.pressedMouseMove || t.vertTouchDrag || i.axisDoubleClickReset.time || i.axisPressedMouseMove.time || i.mouseWheel || i.pinch);
    }
    ru() {
      return 0 === this.D_.length ? null : 0;
    }
    hu() {
      return 0 === this.D_.length ? null : this.D_.length - 1;
    }
    Lu(t) {
      return (this.Mo - 1 - t) / this.q_;
    }
    du(t) {
      const i = this.Lu(t), s = this._u() + this.U_ - i;
      return Math.round(1e6 * s) / 1e6;
    }
    wu(t) {
      const i = this.q_;
      this.q_ = t, this.lu(), i !== this.q_ && (this.E_ = true, this.Ou());
    }
    iu() {
      if (!this.E_) return;
      if (this.E_ = false, this.Ki()) return void this.Nu(Vi.T_());
      const t = this._u(), i = this.Mo / this.q_, s = this.U_ + t, n = new Ti(s - i + 1, s);
      this.Nu(new Vi(n));
    }
    lu() {
      const t = Jt(this.q_, this.Fu(), this.Wu());
      this.q_ !== t && (this.q_ = t, this.E_ = true);
    }
    Wu() {
      return this.Ps.maxBarSpacing > 0 ? this.Ps.maxBarSpacing : 0.5 * this.Mo;
    }
    Fu() {
      return this.Ps.fixLeftEdge && this.Ps.fixRightEdge && 0 !== this.D_.length ? this.Mo / this.D_.length : this.Ps.minBarSpacing;
    }
    ou() {
      const t = this.Hu();
      null !== t && this.U_ < t && (this.U_ = t, this.E_ = true);
      const i = this.Uu();
      this.U_ > i && (this.U_ = i, this.E_ = true);
    }
    Hu() {
      const t = this.ru(), i = this.R_;
      if (null === t || null === i) return null;
      return t - i - 1 + (this.Ps.fixLeftEdge ? this.Mo / this.q_ : Math.min(2, this.D_.length));
    }
    Uu() {
      return this.Ps.fixRightEdge ? 0 : this.Mo / this.q_ - Math.min(2, this.D_.length);
    }
    Pu() {
      this.O_ = { mu: this.mu(), gu: this.gu() };
    }
    yu() {
      this.O_ = null;
    }
    bu(t) {
      let i = this.B_.get(t.weight);
      return void 0 === i && (i = new ki(((t2) => this.$u(t2)), this.o_), this.B_.set(t.weight, i)), i.__(t);
    }
    $u(t) {
      return this.o_.formatTickmark(t, this.bl);
    }
    Nu(t) {
      const i = this.I_;
      this.I_ = t, Ri(i.y_(), this.I_.y_()) || this.A_.p(), Ri(i.k_(), this.I_.k_()) || this.z_.p(), this.Ou();
    }
    Ou() {
      this.N_ = null;
    }
    Z_() {
      this.Ou(), this.B_.clear();
    }
    j_() {
      this.o_.updateFormatter(this.bl);
    }
    G_() {
      if (!this.Ps.fixLeftEdge) return;
      const t = this.ru();
      if (null === t) return;
      const i = this.Pe();
      if (null === i) return;
      const s = i.Uh() - t;
      if (s < 0) {
        const t2 = this.U_ - s - 1;
        this.fn(t2);
      }
      this.lu();
    }
    J_() {
      this.ou(), this.lu();
    }
    fu(t) {
      return !this.Ps.ignoreWhitespaceIndices || (this.F_.get(t) || false);
    }
    pu(t) {
      const i = (function* (t2) {
        const i2 = Math.round(t2), s2 = i2 < t2;
        let n = 1;
        for (; ; ) s2 ? (yield i2 + n, yield i2 - n) : (yield i2 - n, yield i2 + n), n++;
      })(t), s = this.hu();
      for (; s; ) {
        const t2 = i.next().value;
        if (this.F_.get(t2)) return t2;
        if (t2 < 0 || t2 > s) break;
      }
      return t;
    }
    Y_(t) {
      if (void 0 !== t.rightOffsetPixels) {
        const i = t.rightOffsetPixels / (t.barSpacing || this.q_);
        this.ts.fn(i);
      }
    }
  };
  var Ei;
  var Ai;
  var zi;
  var Li;
  var Oi;
  !(function(t) {
    t[t.OnTouchEnd = 0] = "OnTouchEnd", t[t.OnNextTap = 1] = "OnNextTap";
  })(Ei || (Ei = {}));
  var Ni = class {
    constructor(t, i, s) {
      this.qu = [], this.Yu = [], this.Mo = 0, this.ju = null, this.Ku = new d(), this.Xu = new d(), this.Zu = null, this.Gu = t, this.Ps = i, this.o_ = s, this.Sl = new k(this.Ps.layout.colorParsers), this.Ju = new C(this), this.uh = new Ii(this, i.timeScale, this.Ps.localization, s), this.Ct = new X(this, i.crosshair), this.Qu = new Gt(i.crosshair), i.addDefaultPane && (this.tc(0), this.qu[0].Io(2)), this.sc = this.nc(0), this.ec = this.nc(1);
    }
    Ih() {
      this.rc(G.gn());
    }
    ar() {
      this.rc(G.wn());
    }
    Zh() {
      this.rc(new G(1));
    }
    Eh(t) {
      const i = this.hc(t);
      this.rc(i);
    }
    ac() {
      return this.ju;
    }
    lc(t) {
      if (this.ju?.n_ === t?.n_ && this.ju?.e_?.Kn === t?.e_?.Kn) return;
      const i = this.ju;
      this.ju = t, null !== i && this.Eh(i.n_), null !== t && t.n_ !== i?.n_ && this.Eh(t.n_);
    }
    N() {
      return this.Ps;
    }
    hr(t) {
      f(this.Ps, t), this.qu.forEach(((i) => i.Ro(t))), void 0 !== t.timeScale && this.uh.hr(t.timeScale), void 0 !== t.localization && this.uh.X_(t.localization), (t.leftPriceScale || t.rightPriceScale) && this.Ku.p(), this.sc = this.nc(0), this.ec = this.nc(1), this.Ih();
    }
    oc(t, i, s = 0) {
      const n = this.qu[s];
      if (void 0 === n) return;
      if ("left" === t) return f(this.Ps, { leftPriceScale: i }), n.Ro({ leftPriceScale: i }), this.Ku.p(), void this.Ih();
      if ("right" === t) return f(this.Ps, { rightPriceScale: i }), n.Ro({ rightPriceScale: i }), this.Ku.p(), void this.Ih();
      const e3 = this._c(t, s);
      null !== e3 && (e3.Ft.hr(i), this.Ku.p());
    }
    _c(t, i) {
      const s = this.qu[i];
      if (void 0 === s) return null;
      const n = s.Do(t);
      return null !== n ? { Us: s, Ft: n } : null;
    }
    Et() {
      return this.uh;
    }
    $s() {
      return this.qu;
    }
    uc() {
      return this.Ct;
    }
    cc() {
      return this.Xu;
    }
    dc(t, i) {
      t.Al(i), this.vu();
    }
    Eo(t) {
      this.Mo = t, this.uh.Eo(this.Mo), this.qu.forEach(((i) => i.Eo(t))), this.vu();
    }
    fc(t) {
      1 !== this.qu.length && (o(t >= 0 && t < this.qu.length, "Invalid pane index"), this.qu.splice(t, 1), this.Ih());
    }
    vc(t, i) {
      if (this.qu.length < 2) return;
      o(t >= 0 && t < this.qu.length, "Invalid pane index");
      const s = this.qu[t], n = this.qu.reduce(((t2, i2) => t2 + i2.Bo()), 0), e3 = this.qu.reduce(((t2, i2) => t2 + i2.$t()), 0), r2 = e3 - 30 * (this.qu.length - 1);
      i = Math.min(r2, Math.max(30, i));
      const h2 = n / e3, a2 = s.$t();
      s.Io(i * h2);
      let l2 = i - a2, _2 = this.qu.length - 1;
      for (const t2 of this.qu) if (t2 !== s) {
        const i2 = Math.min(r2, Math.max(30, t2.$t() - l2 / _2));
        l2 -= t2.$t() - i2, _2 -= 1;
        const s2 = i2 * h2;
        t2.Io(s2);
      }
      this.Ih();
    }
    mc(t, i) {
      o(t >= 0 && t < this.qu.length && i >= 0 && i < this.qu.length, "Invalid pane index");
      const s = this.qu[t], n = this.qu[i];
      this.qu[t] = n, this.qu[i] = s, this.Ih();
    }
    wc(t, i) {
      if (o(t >= 0 && t < this.qu.length && i >= 0 && i < this.qu.length, "Invalid pane index"), t === i) return;
      const [s] = this.qu.splice(t, 1);
      this.qu.splice(i, 0, s), this.Ih();
    }
    Uo(t, i, s) {
      t.Uo(i, s);
    }
    $o(t, i, s) {
      t.$o(i, s), this.Ah(), this.rc(this.gc(t, 2));
    }
    qo(t, i) {
      t.qo(i), this.rc(this.gc(t, 2));
    }
    Yo(t, i, s) {
      i.Tl() || t.Yo(i, s);
    }
    jo(t, i, s) {
      i.Tl() || (t.jo(i, s), this.Ah(), this.rc(this.gc(t, 2)));
    }
    Ko(t, i) {
      i.Tl() || (t.Ko(i), this.rc(this.gc(t, 2)));
    }
    Zo(t, i) {
      t.Zo(i), this.rc(this.gc(t, 2));
    }
    Mc(t) {
      this.uh.no(t);
    }
    bc(t, i) {
      const s = this.Et();
      if (s.Ki() || 0 === i) return;
      const n = s.Qi();
      t = Math.max(1, Math.min(t, n)), s.Cu(t, i), this.vu();
    }
    Sc(t) {
      this.xc(0), this.Cc(t), this.Pc();
    }
    yc(t) {
      this.uh.eo(t), this.vu();
    }
    kc() {
      this.uh.ro(), this.ar();
    }
    xc(t) {
      this.uh.ho(t);
    }
    Cc(t) {
      this.uh.ao(t), this.vu();
    }
    Pc() {
      this.uh.lo(), this.ar();
    }
    js() {
      return this.Yu;
    }
    Tc(t, i, s, n, e3) {
      this.Ct.Vs(t, i);
      let r2 = NaN, h2 = this.uh.cu(t, true);
      const a2 = this.uh.Pe();
      null !== a2 && (h2 = Math.min(Math.max(a2.Uh(), h2), a2.bi()));
      const l2 = n.ks(), o2 = l2.zt();
      if (null !== o2 && (r2 = l2.Ts(i, o2)), r2 = this.Qu.ga(r2, h2, n), this.Ct.As(h2, r2, n), this.Zh(), !e3) {
        const e4 = yi(n, t, i);
        this.lc(e4 && { n_: e4.n_, e_: e4.e_, h_: e4.h_ || null }), this.Xu.p(this.Ct.It(), { x: t, y: i }, s);
      }
    }
    Rc(t, i, s) {
      const n = s.ks(), e3 = n.zt(), r2 = n.Nt(t, u(e3)), h2 = this.uh.Q_(i, true), a2 = this.uh.qt(u(h2));
      this.Tc(a2, r2, null, s, true);
    }
    Dc(t) {
      this.uc().Ls(), this.Zh(), t || this.Xu.p(null, null, null);
    }
    Ah() {
      const t = this.Ct.Us();
      if (null !== t) {
        const i = this.Ct.Is(), s = this.Ct.Es();
        this.Tc(i, s, null, t);
      }
      this.Ct.Ns();
    }
    Vc(t, i, s) {
      const n = this.uh.Rs(0);
      void 0 !== i && void 0 !== s && this.uh.yt(i, s);
      const e3 = this.uh.Rs(0), r2 = this.uh._u(), h2 = this.uh.Pe();
      if (null !== h2 && null !== n && null !== e3) {
        const i2 = h2.Te(r2), a2 = this.o_.key(n) > this.o_.key(e3), l2 = null !== t && t > r2 && !a2, o2 = this.uh.N().allowShiftVisibleRangeOnWhitespaceReplacement, _2 = i2 && (!(void 0 === s) || o2) && this.uh.N().shiftVisibleRangeOnNewBar;
        if (l2 && !_2) {
          const i3 = t - r2;
          this.uh.fn(this.uh.gu() - i3);
        }
      }
      this.uh.xu(t);
    }
    Lh(t) {
      null !== t && t.Jo();
    }
    Hn(t) {
      if ((function(t2) {
        return t2 instanceof Si;
      })(t)) return t;
      const i = this.qu.find(((i2) => i2.Dt().includes(t)));
      return void 0 === i ? null : i;
    }
    vu() {
      this.qu.forEach(((t) => t.Jo())), this.Ah();
    }
    m() {
      this.qu.forEach(((t) => t.m())), this.qu.length = 0, this.Ps.localization.priceFormatter = void 0, this.Ps.localization.percentageFormatter = void 0, this.Ps.localization.timeFormatter = void 0;
    }
    Bc() {
      return this.Ju;
    }
    Yn() {
      return this.Ju.N();
    }
    Vo() {
      return this.Ku;
    }
    Ic(t, i) {
      const s = this.tc(i);
      this.Ec(t, s), this.Yu.push(t), 1 === this.Yu.length ? this.Ih() : this.ar();
    }
    Ac(t) {
      const i = this.Hn(t), s = this.Yu.indexOf(t);
      o(-1 !== s, "Series not found");
      const n = u(i);
      this.Yu.splice(s, 1), n.Ql(t), t.m && t.m(), this.uh.K_(), this.zc(n);
    }
    Bh(t, i) {
      const s = u(this.Hn(t));
      s.Ql(t, true), s.Gl(t, i, true);
    }
    Au() {
      const t = G.wn();
      t.rn(), this.rc(t);
    }
    Lc(t) {
      const i = G.wn();
      i.ln(t), this.rc(i);
    }
    cn() {
      const t = G.wn();
      t.cn(), this.rc(t);
    }
    dn(t) {
      const i = G.wn();
      i.dn(t), this.rc(i);
    }
    fn(t) {
      const i = G.wn();
      i.fn(t), this.rc(i);
    }
    _n(t) {
      const i = G.wn();
      i._n(t), this.rc(i);
    }
    hn() {
      const t = G.wn();
      t.hn(), this.rc(t);
    }
    Oc() {
      return this.Ps.rightPriceScale.visible ? "right" : "left";
    }
    Nc(t, i) {
      o(i >= 0, "Index should be greater or equal to 0");
      if (i === this.Fc(t)) return;
      const s = u(this.Hn(t));
      s.Ql(t);
      const n = this.tc(i);
      this.Ec(t, n), 0 === s.Ma().length && this.zc(s), this.Ih();
    }
    Wc() {
      return this.ec;
    }
    $() {
      return this.sc;
    }
    Ut(t) {
      const i = this.ec, s = this.sc;
      if (i === s) return i;
      if (t = Math.max(0, Math.min(100, Math.round(100 * t))), null === this.Zu || this.Zu.mr !== s || this.Zu.wr !== i) this.Zu = { mr: s, wr: i, Hc: /* @__PURE__ */ new Map() };
      else {
        const i2 = this.Zu.Hc.get(t);
        if (void 0 !== i2) return i2;
      }
      const n = this.Sl.tt(s, i, t / 100);
      return this.Zu.Hc.set(t, n), n;
    }
    Uc(t) {
      return this.qu.indexOf(t);
    }
    Xi() {
      return this.Sl;
    }
    $c() {
      return this.qc();
    }
    qc(t) {
      const i = new Si(this.uh, this);
      this.qu.push(i);
      const s = t ?? this.qu.length - 1, n = G.gn();
      return n.Qs(s, { tn: 0, sn: true }), this.rc(n), i;
    }
    tc(t) {
      return o(t >= 0, "Index should be greater or equal to 0"), (t = Math.min(this.qu.length, t)) < this.qu.length ? this.qu[t] : this.qc(t);
    }
    Fc(t) {
      return this.qu.findIndex(((i) => i.Oo().includes(t)));
    }
    gc(t, i) {
      const s = new G(i);
      if (null !== t) {
        const n = this.qu.indexOf(t);
        s.Qs(n, { tn: i });
      }
      return s;
    }
    hc(t, i) {
      return void 0 === i && (i = 2), this.gc(this.Hn(t), i);
    }
    rc(t) {
      this.Gu && this.Gu(t), this.qu.forEach(((t2) => t2.i_().lr().yt()));
    }
    Ec(t, i) {
      const s = t.N().priceScaleId, n = void 0 !== s ? s : this.Oc();
      i.Gl(t, n), Z(n) || t.hr(t.N());
    }
    nc(t) {
      const i = this.Ps.layout;
      return "gradient" === i.background.type ? 0 === t ? i.background.topColor : i.background.bottomColor : i.background.color;
    }
    zc(t) {
      !t.Lo() && 0 === t.Ma().length && this.qu.length > 1 && this.qu.splice(this.Uc(t), 1);
    }
  };
  function Fi(t) {
    if (t >= 1) return 0;
    let i = 0;
    for (; i < 8; i++) {
      const s = Math.round(t);
      if (Math.abs(s - t) < 1e-8) return i;
      t *= 10;
    }
    return i;
  }
  function Wi(t) {
    return !p(t) && !m(t);
  }
  function Hi(t) {
    return p(t);
  }
  !(function(t) {
    t[t.Disabled = 0] = "Disabled", t[t.Continuous = 1] = "Continuous", t[t.OnDataUpdate = 2] = "OnDataUpdate";
  })(Ai || (Ai = {})), (function(t) {
    t[t.LastBar = 0] = "LastBar", t[t.LastVisible = 1] = "LastVisible";
  })(zi || (zi = {})), (function(t) {
    t.Solid = "solid", t.VerticalGradient = "gradient";
  })(Li || (Li = {})), (function(t) {
    t[t.Year = 0] = "Year", t[t.Month = 1] = "Month", t[t.DayOfMonth = 2] = "DayOfMonth", t[t.Time = 3] = "Time", t[t.TimeWithSeconds = 4] = "TimeWithSeconds";
  })(Oi || (Oi = {}));
  var Ui = (t) => t.getUTCFullYear();
  function $i(t, i, s) {
    return i.replace(/yyyy/g, ((t2) => tt(Ui(t2), 4))(t)).replace(/yy/g, ((t2) => tt(Ui(t2) % 100, 2))(t)).replace(/MMMM/g, ((t2, i2) => new Date(t2.getUTCFullYear(), t2.getUTCMonth(), 1).toLocaleString(i2, { month: "long" }))(t, s)).replace(/MMM/g, ((t2, i2) => new Date(t2.getUTCFullYear(), t2.getUTCMonth(), 1).toLocaleString(i2, { month: "short" }))(t, s)).replace(/MM/g, ((t2) => tt(((t3) => t3.getUTCMonth() + 1)(t2), 2))(t)).replace(/dd/g, ((t2) => tt(((t3) => t3.getUTCDate())(t2), 2))(t));
  }
  var qi = class {
    constructor(t = "yyyy-MM-dd", i = "default") {
      this.Yc = t, this.jc = i;
    }
    __(t) {
      return $i(t, this.Yc, this.jc);
    }
  };
  var Yi = class {
    constructor(t) {
      this.Kc = t || "%h:%m:%s";
    }
    __(t) {
      return this.Kc.replace("%h", tt(t.getUTCHours(), 2)).replace("%m", tt(t.getUTCMinutes(), 2)).replace("%s", tt(t.getUTCSeconds(), 2));
    }
  };
  var ji = { Xc: "yyyy-MM-dd", Zc: "%h:%m:%s", Gc: " ", Jc: "default" };
  var Ki = class {
    constructor(t = {}) {
      const i = { ...ji, ...t };
      this.Qc = new qi(i.Xc, i.Jc), this.td = new Yi(i.Zc), this.sd = i.Gc;
    }
    __(t) {
      return `${this.Qc.__(t)}${this.sd}${this.td.__(t)}`;
    }
  };
  function Xi(t) {
    return 60 * t * 60 * 1e3;
  }
  function Zi(t) {
    return 60 * t * 1e3;
  }
  var Gi = [{ nd: (Ji = 1, 1e3 * Ji), ed: 10 }, { nd: Zi(1), ed: 20 }, { nd: Zi(5), ed: 21 }, { nd: Zi(30), ed: 22 }, { nd: Xi(1), ed: 30 }, { nd: Xi(3), ed: 31 }, { nd: Xi(6), ed: 32 }, { nd: Xi(12), ed: 33 }];
  var Ji;
  function Qi(t, i) {
    if (t.getUTCFullYear() !== i.getUTCFullYear()) return 70;
    if (t.getUTCMonth() !== i.getUTCMonth()) return 60;
    if (t.getUTCDate() !== i.getUTCDate()) return 50;
    for (let s = Gi.length - 1; s >= 0; --s) if (Math.floor(i.getTime() / Gi[s].nd) !== Math.floor(t.getTime() / Gi[s].nd)) return Gi[s].ed;
    return 0;
  }
  function ts(t) {
    let i = t;
    if (m(t) && (i = ss(t)), !Wi(i)) throw new Error("time must be of type BusinessDay");
    const s = new Date(Date.UTC(i.year, i.month - 1, i.day, 0, 0, 0, 0));
    return { rd: Math.round(s.getTime() / 1e3), hd: i };
  }
  function is(t) {
    if (!Hi(t)) throw new Error("time must be of type isUTCTimestamp");
    return { rd: t };
  }
  function ss(t) {
    const i = new Date(t);
    if (isNaN(i.getTime())) throw new Error(`Invalid date string=${t}, expected format=yyyy-mm-dd`);
    return { day: i.getUTCDate(), month: i.getUTCMonth() + 1, year: i.getUTCFullYear() };
  }
  function ns(t) {
    m(t.time) && (t.time = ss(t.time));
  }
  var es = class {
    options() {
      return this.Ps;
    }
    setOptions(t) {
      this.Ps = t, this.updateFormatter(t.localization);
    }
    preprocessData(t) {
      Array.isArray(t) ? (function(t2) {
        t2.forEach(ns);
      })(t) : ns(t);
    }
    createConverterToInternalObj(t) {
      return u((function(t2) {
        return 0 === t2.length ? null : Wi(t2[0].time) || m(t2[0].time) ? ts : is;
      })(t));
    }
    key(t) {
      return "object" == typeof t && "rd" in t ? t.rd : this.key(this.convertHorzItemToInternal(t));
    }
    cacheKey(t) {
      const i = t;
      return void 0 === i.hd ? new Date(1e3 * i.rd).getTime() : new Date(Date.UTC(i.hd.year, i.hd.month - 1, i.hd.day)).getTime();
    }
    convertHorzItemToInternal(t) {
      return Hi(i = t) ? is(i) : Wi(i) ? ts(i) : ts(ss(i));
      var i;
    }
    updateFormatter(t) {
      if (!this.Ps) return;
      const i = t.dateFormat;
      this.Ps.timeScale.timeVisible ? this.ad = new Ki({ Xc: i, Zc: this.Ps.timeScale.secondsVisible ? "%h:%m:%s" : "%h:%m", Gc: "   ", Jc: t.locale }) : this.ad = new qi(i, t.locale);
    }
    formatHorzItem(t) {
      const i = t;
      return this.ad.__(new Date(1e3 * i.rd));
    }
    formatTickmark(t, i) {
      const s = (function(t2, i2, s2) {
        switch (t2) {
          case 0:
          case 10:
            return i2 ? s2 ? 4 : 3 : 2;
          case 20:
          case 21:
          case 22:
          case 30:
          case 31:
          case 32:
          case 33:
            return i2 ? 3 : 2;
          case 50:
            return 2;
          case 60:
            return 1;
          case 70:
            return 0;
        }
      })(t.weight, this.Ps.timeScale.timeVisible, this.Ps.timeScale.secondsVisible), n = this.Ps.timeScale;
      if (void 0 !== n.tickMarkFormatter) {
        const e3 = n.tickMarkFormatter(t.originalTime, s, i.locale);
        if (null !== e3) return e3;
      }
      return (function(t2, i2, s2) {
        const n2 = {};
        switch (i2) {
          case 0:
            n2.year = "numeric";
            break;
          case 1:
            n2.month = "short";
            break;
          case 2:
            n2.day = "numeric";
            break;
          case 3:
            n2.hour12 = false, n2.hour = "2-digit", n2.minute = "2-digit";
            break;
          case 4:
            n2.hour12 = false, n2.hour = "2-digit", n2.minute = "2-digit", n2.second = "2-digit";
        }
        const e3 = void 0 === t2.hd ? new Date(1e3 * t2.rd) : new Date(Date.UTC(t2.hd.year, t2.hd.month - 1, t2.hd.day));
        return new Date(e3.getUTCFullYear(), e3.getUTCMonth(), e3.getUTCDate(), e3.getUTCHours(), e3.getUTCMinutes(), e3.getUTCSeconds(), e3.getUTCMilliseconds()).toLocaleString(s2, n2);
      })(t.time, s, i.locale);
    }
    maxTickMarkWeight(t) {
      let i = t.reduce(Bi, t[0]).weight;
      return i > 30 && i < 50 && (i = 30), i;
    }
    fillWeightsForPoints(t, i) {
      !(function(t2, i2 = 0) {
        if (0 === t2.length) return;
        let s = 0 === i2 ? null : t2[i2 - 1].time.rd, n = null !== s ? new Date(1e3 * s) : null, e3 = 0;
        for (let r2 = i2; r2 < t2.length; ++r2) {
          const i3 = t2[r2], h2 = new Date(1e3 * i3.time.rd);
          null !== n && (i3.timeWeight = Qi(h2, n)), e3 += i3.time.rd - (s || i3.time.rd), s = i3.time.rd, n = h2;
        }
        if (0 === i2 && t2.length > 1) {
          const i3 = Math.ceil(e3 / (t2.length - 1)), s2 = new Date(1e3 * (t2[0].time.rd - i3));
          t2[0].timeWeight = Qi(new Date(1e3 * t2[0].time.rd), s2);
        }
      })(t, i);
    }
    static ld(t) {
      return f({ localization: { dateFormat: "dd MMM 'yy" } }, t ?? {});
    }
  };
  var rs = "undefined" != typeof window;
  function hs() {
    return !!rs && window.navigator.userAgent.toLowerCase().indexOf("firefox") > -1;
  }
  function as() {
    return !!rs && /iPhone|iPad|iPod/.test(window.navigator.platform);
  }
  function ls(t) {
    return t + t % 2;
  }
  function os(t) {
    rs && void 0 !== window.chrome && t.addEventListener("mousedown", ((t2) => {
      if (1 === t2.button) return t2.preventDefault(), false;
    }));
  }
  var _s = class {
    constructor(t, i, s) {
      this.od = 0, this._d = null, this.ud = { _t: Number.NEGATIVE_INFINITY, ut: Number.POSITIVE_INFINITY }, this.dd = 0, this.fd = null, this.pd = { _t: Number.NEGATIVE_INFINITY, ut: Number.POSITIVE_INFINITY }, this.vd = null, this.md = false, this.wd = null, this.gd = null, this.Md = false, this.bd = false, this.Sd = false, this.xd = null, this.Cd = null, this.Pd = null, this.yd = null, this.kd = null, this.Td = null, this.Rd = null, this.Dd = 0, this.Vd = false, this.Bd = false, this.Id = false, this.Ed = 0, this.Ad = null, this.zd = !as(), this.Ld = (t2) => {
        this.Od(t2);
      }, this.Nd = (t2) => {
        if (this.Fd(t2)) {
          const i2 = this.Wd(t2);
          if (++this.dd, this.fd && this.dd > 1) {
            const { Hd: s2 } = this.Ud(ds(t2), this.pd);
            s2 < 30 && !this.Sd && this.$d(i2, this.Yd.qd), this.jd();
          }
        } else {
          const i2 = this.Wd(t2);
          if (++this.od, this._d && this.od > 1) {
            const { Hd: s2 } = this.Ud(ds(t2), this.ud);
            s2 < 5 && !this.bd && this.Kd(i2, this.Yd.Xd), this.Zd();
          }
        }
      }, this.Gd = t, this.Yd = i, this.Ps = s, this.Jd();
    }
    m() {
      null !== this.xd && (this.xd(), this.xd = null), null !== this.Cd && (this.Cd(), this.Cd = null), null !== this.yd && (this.yd(), this.yd = null), null !== this.kd && (this.kd(), this.kd = null), null !== this.Td && (this.Td(), this.Td = null), null !== this.Pd && (this.Pd(), this.Pd = null), this.Qd(), this.Zd();
    }
    tf(t) {
      this.yd && this.yd();
      const i = this.if.bind(this);
      if (this.yd = () => {
        this.Gd.removeEventListener("mousemove", i);
      }, this.Gd.addEventListener("mousemove", i), this.Fd(t)) return;
      const s = this.Wd(t);
      this.Kd(s, this.Yd.sf), this.zd = true;
    }
    Zd() {
      null !== this._d && clearTimeout(this._d), this.od = 0, this._d = null, this.ud = { _t: Number.NEGATIVE_INFINITY, ut: Number.POSITIVE_INFINITY };
    }
    jd() {
      null !== this.fd && clearTimeout(this.fd), this.dd = 0, this.fd = null, this.pd = { _t: Number.NEGATIVE_INFINITY, ut: Number.POSITIVE_INFINITY };
    }
    if(t) {
      if (this.Id || null !== this.gd) return;
      if (this.Fd(t)) return;
      const i = this.Wd(t);
      this.Kd(i, this.Yd.nf), this.zd = true;
    }
    ef(t) {
      const i = ps(t.changedTouches, u(this.Ad));
      if (null === i) return;
      if (this.Ed = fs(t), null !== this.Rd) return;
      if (this.Bd) return;
      this.Vd = true;
      const s = this.Ud(ds(i), u(this.gd)), { rf: n, hf: e3, Hd: r2 } = s;
      if (this.Md || !(r2 < 5)) {
        if (!this.Md) {
          const t2 = 0.5 * n, i2 = e3 >= t2 && !this.Ps.af(), s2 = t2 > e3 && !this.Ps.lf();
          i2 || s2 || (this.Bd = true), this.Md = true, this.Sd = true, this.Qd(), this.jd();
        }
        if (!this.Bd) {
          const s2 = this.Wd(t, i);
          this.$d(s2, this.Yd._f), cs(t);
        }
      }
    }
    uf(t) {
      if (0 !== t.button) return;
      const i = this.Ud(ds(t), u(this.wd)), { Hd: s } = i;
      if (s >= 5 && (this.bd = true, this.Zd()), this.bd) {
        const i2 = this.Wd(t);
        this.Kd(i2, this.Yd.cf);
      }
    }
    Ud(t, i) {
      const s = Math.abs(i._t - t._t), n = Math.abs(i.ut - t.ut);
      return { rf: s, hf: n, Hd: s + n };
    }
    df(t) {
      let i = ps(t.changedTouches, u(this.Ad));
      if (null === i && 0 === t.touches.length && (i = t.changedTouches[0]), null === i) return;
      this.Ad = null, this.Ed = fs(t), this.Qd(), this.gd = null, this.Td && (this.Td(), this.Td = null);
      const s = this.Wd(t, i);
      if (this.$d(s, this.Yd.ff), ++this.dd, this.fd && this.dd > 1) {
        const { Hd: t2 } = this.Ud(ds(i), this.pd);
        t2 < 30 && !this.Sd && this.$d(s, this.Yd.qd), this.jd();
      } else this.Sd || (this.$d(s, this.Yd.pf), this.Yd.pf && cs(t));
      0 === this.dd && cs(t), 0 === t.touches.length && this.md && (this.md = false, cs(t));
    }
    Od(t) {
      if (0 !== t.button) return;
      const i = this.Wd(t);
      if (this.wd = null, this.Id = false, this.kd && (this.kd(), this.kd = null), hs()) {
        this.Gd.ownerDocument.documentElement.removeEventListener("mouseleave", this.Ld);
      }
      if (!this.Fd(t)) if (this.Kd(i, this.Yd.vf), ++this.od, this._d && this.od > 1) {
        const { Hd: s } = this.Ud(ds(t), this.ud);
        s < 5 && !this.bd && this.Kd(i, this.Yd.Xd), this.Zd();
      } else this.bd || this.Kd(i, this.Yd.mf);
    }
    Qd() {
      null !== this.vd && (clearTimeout(this.vd), this.vd = null);
    }
    wf(t) {
      if (null !== this.Ad) return;
      const i = t.changedTouches[0];
      this.Ad = i.identifier, this.Ed = fs(t);
      const s = this.Gd.ownerDocument.documentElement;
      this.Sd = false, this.Md = false, this.Bd = false, this.gd = ds(i), this.Td && (this.Td(), this.Td = null);
      {
        const i2 = this.ef.bind(this), n2 = this.df.bind(this);
        this.Td = () => {
          s.removeEventListener("touchmove", i2), s.removeEventListener("touchend", n2);
        }, s.addEventListener("touchmove", i2, { passive: false }), s.addEventListener("touchend", n2, { passive: false }), this.Qd(), this.vd = setTimeout(this.gf.bind(this, t), 240);
      }
      const n = this.Wd(t, i);
      this.$d(n, this.Yd.Mf), this.fd || (this.dd = 0, this.fd = setTimeout(this.jd.bind(this), 500), this.pd = ds(i));
    }
    bf(t) {
      if (0 !== t.button) return;
      const i = this.Gd.ownerDocument.documentElement;
      hs() && i.addEventListener("mouseleave", this.Ld), this.bd = false, this.wd = ds(t), this.kd && (this.kd(), this.kd = null);
      {
        const t2 = this.uf.bind(this), s2 = this.Od.bind(this);
        this.kd = () => {
          i.removeEventListener("mousemove", t2), i.removeEventListener("mouseup", s2);
        }, i.addEventListener("mousemove", t2), i.addEventListener("mouseup", s2);
      }
      if (this.Id = true, this.Fd(t)) return;
      const s = this.Wd(t);
      this.Kd(s, this.Yd.Sf), this._d || (this.od = 0, this._d = setTimeout(this.Zd.bind(this), 500), this.ud = ds(t));
    }
    Jd() {
      this.Gd.addEventListener("mouseenter", this.tf.bind(this)), this.Gd.addEventListener("touchcancel", this.Qd.bind(this));
      {
        const t = this.Gd.ownerDocument, i = (t2) => {
          this.Yd.xf && (t2.composed && this.Gd.contains(t2.composedPath()[0]) || t2.target && this.Gd.contains(t2.target) || this.Yd.xf());
        };
        this.Cd = () => {
          t.removeEventListener("touchstart", i);
        }, this.xd = () => {
          t.removeEventListener("mousedown", i);
        }, t.addEventListener("mousedown", i), t.addEventListener("touchstart", i, { passive: true });
      }
      as() && (this.Pd = () => {
        this.Gd.removeEventListener("dblclick", this.Nd);
      }, this.Gd.addEventListener("dblclick", this.Nd)), this.Gd.addEventListener("mouseleave", this.Cf.bind(this)), this.Gd.addEventListener("touchstart", this.wf.bind(this), { passive: true }), os(this.Gd), this.Gd.addEventListener("mousedown", this.bf.bind(this)), this.Pf(), this.Gd.addEventListener("touchmove", (() => {
      }), { passive: false });
    }
    Pf() {
      void 0 === this.Yd.yf && void 0 === this.Yd.kf && void 0 === this.Yd.Tf || (this.Gd.addEventListener("touchstart", ((t) => this.Rf(t.touches)), { passive: true }), this.Gd.addEventListener("touchmove", ((t) => {
        if (2 === t.touches.length && null !== this.Rd && void 0 !== this.Yd.kf) {
          const i = us(t.touches[0], t.touches[1]) / this.Dd;
          this.Yd.kf(this.Rd, i), cs(t);
        }
      }), { passive: false }), this.Gd.addEventListener("touchend", ((t) => {
        this.Rf(t.touches);
      })));
    }
    Rf(t) {
      1 === t.length && (this.Vd = false), 2 !== t.length || this.Vd || this.md ? this.Df() : this.Vf(t);
    }
    Vf(t) {
      const i = this.Gd.getBoundingClientRect() || { left: 0, top: 0 };
      this.Rd = { _t: (t[0].clientX - i.left + (t[1].clientX - i.left)) / 2, ut: (t[0].clientY - i.top + (t[1].clientY - i.top)) / 2 }, this.Dd = us(t[0], t[1]), void 0 !== this.Yd.yf && this.Yd.yf(), this.Qd();
    }
    Df() {
      null !== this.Rd && (this.Rd = null, void 0 !== this.Yd.Tf && this.Yd.Tf());
    }
    Cf(t) {
      if (this.yd && this.yd(), this.Fd(t)) return;
      if (!this.zd) return;
      const i = this.Wd(t);
      this.Kd(i, this.Yd.Bf), this.zd = !as();
    }
    gf(t) {
      const i = ps(t.touches, u(this.Ad));
      if (null === i) return;
      const s = this.Wd(t, i);
      this.$d(s, this.Yd.If), this.Sd = true, this.md = true;
    }
    Fd(t) {
      return t.sourceCapabilities && void 0 !== t.sourceCapabilities.firesTouchEvents ? t.sourceCapabilities.firesTouchEvents : fs(t) < this.Ed + 500;
    }
    $d(t, i) {
      i && i.call(this.Yd, t);
    }
    Kd(t, i) {
      i && i.call(this.Yd, t);
    }
    Wd(t, i) {
      const s = i || t, n = this.Gd.getBoundingClientRect() || { left: 0, top: 0 };
      return { clientX: s.clientX, clientY: s.clientY, pageX: s.pageX, pageY: s.pageY, screenX: s.screenX, screenY: s.screenY, localX: s.clientX - n.left, localY: s.clientY - n.top, ctrlKey: t.ctrlKey, altKey: t.altKey, shiftKey: t.shiftKey, metaKey: t.metaKey, Ef: !t.type.startsWith("mouse") && "contextmenu" !== t.type && "click" !== t.type, Af: t.type, zf: s.target, a_: t.view, Lf: () => {
        "touchstart" !== t.type && cs(t);
      } };
    }
  };
  function us(t, i) {
    const s = t.clientX - i.clientX, n = t.clientY - i.clientY;
    return Math.sqrt(s * s + n * n);
  }
  function cs(t) {
    t.cancelable && t.preventDefault();
  }
  function ds(t) {
    return { _t: t.pageX, ut: t.pageY };
  }
  function fs(t) {
    return t.timeStamp || performance.now();
  }
  function ps(t, i) {
    for (let s = 0; s < t.length; ++s) if (t[s].identifier === i) return t[s];
    return null;
  }
  var vs = class {
    constructor(t, i, s) {
      this.Of = null, this.Nf = null, this.Ff = true, this.Wf = null, this.Hf = t, this.Uf = t.$f()[i], this.qf = t.$f()[s], this.Yf = document.createElement("tr"), this.Yf.style.height = "1px", this.jf = document.createElement("td"), this.jf.style.position = "relative", this.jf.style.padding = "0", this.jf.style.margin = "0", this.jf.setAttribute("colspan", "3"), this.Kf(), this.Yf.appendChild(this.jf), this.Ff = this.Hf.N().layout.panes.enableResize, this.Ff ? this.Xf() : (this.Of = null, this.Nf = null);
    }
    m() {
      null !== this.Nf && this.Nf.m();
    }
    Zf() {
      return this.Yf;
    }
    Gf() {
      return size({ width: this.Uf.Gf().width, height: 1 });
    }
    Jf() {
      return size({ width: this.Uf.Jf().width, height: 1 * window.devicePixelRatio });
    }
    Qf(t, i, s) {
      const n = this.Jf();
      t.fillStyle = this.Hf.N().layout.panes.separatorColor, t.fillRect(i, s, n.width, n.height);
    }
    yt() {
      this.Kf(), this.Hf.N().layout.panes.enableResize !== this.Ff && (this.Ff = this.Hf.N().layout.panes.enableResize, this.Ff ? this.Xf() : (null !== this.Of && (this.jf.removeChild(this.Of.tp), this.jf.removeChild(this.Of.ip), this.Of = null), null !== this.Nf && (this.Nf.m(), this.Nf = null)));
    }
    Xf() {
      const t = document.createElement("div"), i = t.style;
      i.position = "fixed", i.display = "none", i.zIndex = "49", i.top = "0", i.left = "0", i.width = "100%", i.height = "100%", i.cursor = "row-resize", this.jf.appendChild(t);
      const s = document.createElement("div"), n = s.style;
      n.position = "absolute", n.zIndex = "50", n.top = "-4px", n.height = "9px", n.width = "100%", n.backgroundColor = "", n.cursor = "row-resize", this.jf.appendChild(s);
      const e3 = { sf: this.sp.bind(this), Bf: this.np.bind(this), Sf: this.ep.bind(this), Mf: this.ep.bind(this), cf: this.rp.bind(this), _f: this.rp.bind(this), vf: this.hp.bind(this), ff: this.hp.bind(this) };
      this.Nf = new _s(s, e3, { af: () => false, lf: () => true }), this.Of = { ip: s, tp: t };
    }
    Kf() {
      this.jf.style.background = this.Hf.N().layout.panes.separatorColor;
    }
    sp(t) {
      null !== this.Of && (this.Of.ip.style.backgroundColor = this.Hf.N().layout.panes.separatorHoverColor);
    }
    np(t) {
      null !== this.Of && null === this.Wf && (this.Of.ip.style.backgroundColor = "");
    }
    ep(t) {
      if (null === this.Of) return;
      const i = this.Uf.ap().Bo() + this.qf.ap().Bo(), s = i / (this.Uf.Gf().height + this.qf.Gf().height), n = 30 * s;
      i <= 2 * n || (this.Wf = { lp: t.pageY, op: this.Uf.ap().Bo(), _p: i - n, up: i, cp: s, dp: n }, this.Of.tp.style.display = "block");
    }
    rp(t) {
      const i = this.Wf;
      if (null === i) return;
      const s = (t.pageY - i.lp) * i.cp, n = Jt(i.op + s, i.dp, i._p);
      this.Uf.ap().Io(n), this.qf.ap().Io(i.up - n), this.Hf.Qt().Ih();
    }
    hp(t) {
      null !== this.Wf && null !== this.Of && (this.Wf = null, this.Of.tp.style.display = "none");
    }
  };
  function ms(t, i) {
    return t.fp - i.fp;
  }
  function ws(t, i, s) {
    const n = (t.fp - i.fp) / (t.wt - i.wt);
    return Math.sign(n) * Math.min(Math.abs(n), s);
  }
  var gs = class {
    constructor(t, i, s, n) {
      this.pp = null, this.vp = null, this.mp = null, this.wp = null, this.gp = null, this.Mp = 0, this.bp = 0, this.Sp = t, this.xp = i, this.Cp = s, this.Mn = n;
    }
    Pp(t, i) {
      if (null !== this.pp) {
        if (this.pp.wt === i) return void (this.pp.fp = t);
        if (Math.abs(this.pp.fp - t) < this.Mn) return;
      }
      this.wp = this.mp, this.mp = this.vp, this.vp = this.pp, this.pp = { wt: i, fp: t };
    }
    le(t, i) {
      if (null === this.pp || null === this.vp) return;
      if (i - this.pp.wt > 50) return;
      let s = 0;
      const n = ws(this.pp, this.vp, this.xp), e3 = ms(this.pp, this.vp), r2 = [n], h2 = [e3];
      if (s += e3, null !== this.mp) {
        const t2 = ws(this.vp, this.mp, this.xp);
        if (Math.sign(t2) === Math.sign(n)) {
          const i2 = ms(this.vp, this.mp);
          if (r2.push(t2), h2.push(i2), s += i2, null !== this.wp) {
            const t3 = ws(this.mp, this.wp, this.xp);
            if (Math.sign(t3) === Math.sign(n)) {
              const i3 = ms(this.mp, this.wp);
              r2.push(t3), h2.push(i3), s += i3;
            }
          }
        }
      }
      let a2 = 0;
      for (let t2 = 0; t2 < r2.length; ++t2) a2 += h2[t2] / s * r2[t2];
      Math.abs(a2) < this.Sp || (this.gp = { fp: t, wt: i }, this.bp = a2, this.Mp = (function(t2, i2) {
        const s2 = Math.log(i2);
        return Math.log(1 * s2 / -t2) / s2;
      })(Math.abs(a2), this.Cp));
    }
    Du(t) {
      const i = u(this.gp), s = t - i.wt;
      return i.fp + this.bp * (Math.pow(this.Cp, s) - 1) / Math.log(this.Cp);
    }
    Ru(t) {
      return null === this.gp || this.yp(t) === this.Mp;
    }
    yp(t) {
      const i = t - u(this.gp).wt;
      return Math.min(i, this.Mp);
    }
  };
  var Ms = class {
    constructor(t, i) {
      this.kp = void 0, this.Tp = void 0, this.Rp = void 0, this.ps = false, this.Dp = t, this.Vp = i, this.Bp();
    }
    yt() {
      this.Bp();
    }
    Ip() {
      this.kp && this.Dp.removeChild(this.kp), this.Tp && this.Dp.removeChild(this.Tp), this.kp = void 0, this.Tp = void 0;
    }
    Ep() {
      return this.ps !== this.Ap() || this.Rp !== this.zp();
    }
    zp() {
      return this.Vp.Qt().Xi().J(this.Vp.N().layout.textColor) > 160 ? "dark" : "light";
    }
    Ap() {
      return this.Vp.N().layout.attributionLogo;
    }
    Lp() {
      const t = new URL(location.href);
      return t.hostname ? "&utm_source=" + t.hostname + t.pathname : "";
    }
    Bp() {
      this.Ep() && (this.Ip(), this.ps = this.Ap(), this.ps && (this.Rp = this.zp(), this.Tp = document.createElement("style"), this.Tp.innerText = "a#tv-attr-logo{--fill:#131722;--stroke:#fff;position:absolute;left:10px;bottom:10px;height:19px;width:35px;margin:0;padding:0;border:0;z-index:3;}a#tv-attr-logo[data-dark]{--fill:#D1D4DC;--stroke:#131722;}", this.kp = document.createElement("a"), this.kp.href = `https://www.tradingview.com/?utm_medium=lwc-link&utm_campaign=lwc-chart${this.Lp()}`, this.kp.title = "Charting by TradingView", this.kp.id = "tv-attr-logo", this.kp.target = "_blank", this.kp.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="35" height="19" fill="none"><g fill-rule="evenodd" clip-path="url(#a)" clip-rule="evenodd"><path fill="var(--stroke)" d="M2 0H0v10h6v9h21.4l.5-1.3 6-15 1-2.7H23.7l-.5 1.3-.2.6a5 5 0 0 0-7-.9V0H2Zm20 17h4l5.2-13 .8-2h-7l-1 2.5-.2.5-1.5 3.8-.3.7V17Zm-.8-10a3 3 0 0 0 .7-2.7A3 3 0 1 0 16.8 7h4.4ZM14 7V2H2v6h6v9h4V7h2Z"/><path fill="var(--fill)" d="M14 2H2v6h6v9h6V2Zm12 15h-7l6-15h7l-6 15Zm-7-9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/></g><defs><clipPath id="a"><path fill="var(--stroke)" d="M0 0h35v19H0z"/></clipPath></defs></svg>', this.kp.toggleAttribute("data-dark", "dark" === this.Rp), this.Dp.appendChild(this.Tp), this.Dp.appendChild(this.kp)));
    }
  };
  function bs(t, s) {
    const n = u(t.ownerDocument).createElement("canvas");
    t.appendChild(n);
    const e3 = bindTo(n, { type: "device-pixel-content-box", options: { allowResizeObserver: true }, transform: (t2, i) => ({ width: Math.max(t2.width, i.width), height: Math.max(t2.height, i.height) }) });
    return e3.resizeCanvasElement(s), e3;
  }
  function Ss(t) {
    t.width = 1, t.height = 1, t.getContext("2d")?.clearRect(0, 0, 1, 1);
  }
  function xs(t, i, s, n) {
    t.ih && t.ih(i, s, n);
  }
  function Cs(t, i, s, n) {
    t.nt(i, s, n);
  }
  function Ps(t, i, s, n) {
    const e3 = t(s, n);
    for (const t2 of e3) {
      const s2 = t2.Tt(n);
      null !== s2 && i(s2);
    }
  }
  function ys(t, i) {
    return (s) => {
      if (!(function(t2) {
        return void 0 !== t2.Ft;
      })(s)) return [];
      return (s.Ft()?.ma() ?? "") !== i ? [] : s.ta?.(t) ?? [];
    };
  }
  function ks(t, i, s, n) {
    if (!t.length) return;
    let e3 = 0;
    const r2 = t[0].$t(n, true);
    let h2 = 1 === i ? s / 2 - (t[0].Fi() - r2 / 2) : t[0].Fi() - r2 / 2 - s / 2;
    h2 = Math.max(0, h2);
    for (let r3 = 1; r3 < t.length; r3++) {
      const a2 = t[r3], l2 = t[r3 - 1], o2 = l2.$t(n, false), _2 = a2.Fi(), u2 = l2.Fi();
      if (1 === i ? _2 > u2 - o2 : _2 < u2 + o2) {
        const n2 = u2 - o2 * i;
        a2.Wi(n2);
        const r4 = n2 - i * o2 / 2;
        if ((1 === i ? r4 < 0 : r4 > s) && h2 > 0) {
          const n3 = 1 === i ? -1 - r4 : r4 - s, a3 = Math.min(n3, h2);
          for (let s2 = e3; s2 < t.length; s2++) t[s2].Wi(t[s2].Fi() + i * a3);
          h2 -= a3;
        }
      } else e3 = r3, h2 = 1 === i ? u2 - o2 - _2 : _2 - (u2 + o2);
    }
  }
  var Ts = class {
    constructor(i, s, n, e3) {
      this.Yi = null, this.Op = null, this.Np = false, this.Fp = new rt(200), this.Wp = null, this.Hp = 0, this.Up = false, this.$p = () => {
        this.Up || this.Pt.qp().Qt().ar();
      }, this.Yp = () => {
        this.Up || this.Pt.qp().Qt().ar();
      }, this.Pt = i, this.Ps = s, this.Ml = s.layout, this.Ju = n, this.jp = "left" === e3, this.Kp = ys("normal", e3), this.Xp = ys("top", e3), this.Zp = ys("bottom", e3), this.jf = document.createElement("div"), this.jf.style.height = "100%", this.jf.style.overflow = "hidden", this.jf.style.width = "25px", this.jf.style.left = "0", this.jf.style.position = "relative", this.Gp = bs(this.jf, size({ width: 16, height: 16 })), this.Gp.subscribeSuggestedBitmapSizeChanged(this.$p);
      const r2 = this.Gp.canvasElement;
      r2.style.position = "absolute", r2.style.zIndex = "1", r2.style.left = "0", r2.style.top = "0", this.Jp = bs(this.jf, size({ width: 16, height: 16 })), this.Jp.subscribeSuggestedBitmapSizeChanged(this.Yp);
      const h2 = this.Jp.canvasElement;
      h2.style.position = "absolute", h2.style.zIndex = "2", h2.style.left = "0", h2.style.top = "0";
      const a2 = { Sf: this.ep.bind(this), Mf: this.ep.bind(this), cf: this.rp.bind(this), _f: this.rp.bind(this), xf: this.Qp.bind(this), vf: this.hp.bind(this), ff: this.hp.bind(this), Xd: this.tv.bind(this), qd: this.tv.bind(this), sf: this.iv.bind(this), Bf: this.np.bind(this) };
      this.Nf = new _s(this.Jp.canvasElement, a2, { af: () => !this.Ps.handleScroll.vertTouchDrag, lf: () => true });
    }
    m() {
      this.Nf.m(), this.Jp.unsubscribeSuggestedBitmapSizeChanged(this.Yp), Ss(this.Jp.canvasElement), this.Jp.dispose(), this.Gp.unsubscribeSuggestedBitmapSizeChanged(this.$p), Ss(this.Gp.canvasElement), this.Gp.dispose(), null !== this.Yi && this.Yi.so().u(this), this.Yi = null;
    }
    Zf() {
      return this.jf;
    }
    P() {
      return this.Ml.fontSize;
    }
    sv() {
      const t = this.Ju.N();
      return this.Wp !== t.k && (this.Fp.Bn(), this.Wp = t.k), t;
    }
    nv() {
      if (null === this.Yi) return 0;
      let t = 0;
      const i = this.sv(), s = u(this.Gp.canvasElement.getContext("2d", { colorSpace: this.Pt.qp().N().layout.colorSpace }));
      s.save();
      const n = this.Yi.Da();
      s.font = this.ev(), n.length > 0 && (t = Math.max(this.Fp.Vi(s, n[0].Za), this.Fp.Vi(s, n[n.length - 1].Za)));
      const e3 = this.rv();
      for (let i2 = e3.length; i2--; ) {
        const n2 = this.Fp.Vi(s, e3[i2].ri());
        n2 > t && (t = n2);
      }
      const r2 = this.Yi.zt();
      if (null !== r2 && null !== this.Op && (2 !== (h2 = this.Ps.crosshair).mode && h2.horzLine.visible && h2.horzLine.labelVisible)) {
        const i2 = this.Yi.Ts(1, r2), n2 = this.Yi.Ts(this.Op.height - 2, r2);
        t = Math.max(t, this.Fp.Vi(s, this.Yi.Zi(Math.floor(Math.min(i2, n2)) + 0.11111111111111, r2)), this.Fp.Vi(s, this.Yi.Zi(Math.ceil(Math.max(i2, n2)) - 0.11111111111111, r2)));
      }
      var h2;
      s.restore();
      const a2 = t || 34;
      return ls(Math.ceil(i.S + i.C + i.B + i.I + 5 + a2));
    }
    hv(t) {
      null !== this.Op && equalSizes(this.Op, t) || (this.Op = t, this.Up = true, this.Gp.resizeCanvasElement(t), this.Jp.resizeCanvasElement(t), this.Up = false, this.jf.style.width = `${t.width}px`, this.jf.style.height = `${t.height}px`);
    }
    av() {
      return u(this.Op).width;
    }
    _s(t) {
      this.Yi !== t && (null !== this.Yi && this.Yi.so().u(this), this.Yi = t, t.so().i(this._l.bind(this), this));
    }
    Ft() {
      return this.Yi;
    }
    Bn() {
      const t = this.Pt.ap();
      this.Pt.qp().Qt().Zo(t, u(this.Ft()));
    }
    lv(t) {
      if (null === this.Op) return;
      const i = { colorSpace: this.Pt.qp().N().layout.colorSpace };
      if (1 !== t) {
        this.ov(), this.Gp.applySuggestedBitmapSize();
        const t2 = tryCreateCanvasRenderingTarget2D(this.Gp, i);
        null !== t2 && (t2.useBitmapCoordinateSpace(((t3) => {
          this._v(t3), this.uv(t3);
        })), this.Pt.cv(t2, this.Zp), this.dv(t2), this.Pt.cv(t2, this.Kp), this.fv(t2));
      }
      this.Jp.applySuggestedBitmapSize();
      const s = tryCreateCanvasRenderingTarget2D(this.Jp, i);
      null !== s && (s.useBitmapCoordinateSpace((({ context: t2, bitmapSize: i2 }) => {
        t2.clearRect(0, 0, i2.width, i2.height);
      })), this.pv(s), this.Pt.cv(s, this.Xp));
    }
    Jf() {
      return this.Gp.bitmapSize;
    }
    Qf(t, i, s, n) {
      const e3 = this.Jf();
      if (e3.width > 0 && e3.height > 0 && (t.drawImage(this.Gp.canvasElement, i, s), n)) {
        const n2 = this.Jp.canvasElement;
        t.drawImage(n2, i, s);
      }
    }
    yt() {
      this.Yi?.Da();
    }
    ep(t) {
      if (null === this.Yi || this.Yi.Ki() || !this.Ps.handleScale.axisPressedMouseMove.price) return;
      const i = this.Pt.qp().Qt(), s = this.Pt.ap();
      this.Np = true, i.Uo(s, this.Yi, t.localY);
    }
    rp(t) {
      if (null === this.Yi || !this.Ps.handleScale.axisPressedMouseMove.price) return;
      const i = this.Pt.qp().Qt(), s = this.Pt.ap(), n = this.Yi;
      i.$o(s, n, t.localY);
    }
    Qp() {
      if (null === this.Yi || !this.Ps.handleScale.axisPressedMouseMove.price) return;
      const t = this.Pt.qp().Qt(), i = this.Pt.ap(), s = this.Yi;
      this.Np && (this.Np = false, t.qo(i, s));
    }
    hp(t) {
      if (null === this.Yi || !this.Ps.handleScale.axisPressedMouseMove.price) return;
      const i = this.Pt.qp().Qt(), s = this.Pt.ap();
      this.Np = false, i.qo(s, this.Yi);
    }
    tv(t) {
      this.Ps.handleScale.axisDoubleClickReset.price && this.Bn();
    }
    iv(t) {
      if (null === this.Yi) return;
      !this.Pt.qp().Qt().N().handleScale.axisPressedMouseMove.price || this.Yi.Le() || this.Yi.Dl() || this.vv(1);
    }
    np(t) {
      this.vv(0);
    }
    rv() {
      const t = [], i = null === this.Yi ? void 0 : this.Yi;
      return ((s) => {
        for (let n = 0; n < s.length; ++n) {
          const e3 = s[n].Ws(this.Pt.ap(), i);
          for (let i2 = 0; i2 < e3.length; i2++) t.push(e3[i2]);
        }
      })(this.Pt.ap().Dt()), t;
    }
    _v({ context: t, bitmapSize: i }) {
      const { width: s, height: n } = i, e3 = this.Pt.ap().Qt(), r2 = e3.$(), h2 = e3.Wc();
      r2 === h2 ? L(t, 0, 0, s, n, r2) : F(t, 0, 0, s, n, r2, h2);
    }
    uv({ context: t, bitmapSize: i, horizontalPixelRatio: s }) {
      if (null === this.Op || null === this.Yi || !this.Yi.N().borderVisible) return;
      t.fillStyle = this.Yi.N().borderColor;
      const n = Math.max(1, Math.floor(this.sv().S * s));
      let e3;
      e3 = this.jp ? i.width - n : 0, t.fillRect(e3, 0, n, i.height);
    }
    dv(t) {
      if (null === this.Op || null === this.Yi) return;
      const i = this.Yi.Da(), s = this.Yi.N(), n = this.sv(), e3 = this.jp ? this.Op.width - n.C : 0;
      s.borderVisible && s.ticksVisible && t.useBitmapCoordinateSpace((({ context: t2, horizontalPixelRatio: r2, verticalPixelRatio: h2 }) => {
        t2.fillStyle = s.borderColor;
        const a2 = Math.max(1, Math.floor(h2)), l2 = Math.floor(0.5 * h2), o2 = Math.round(n.C * r2);
        t2.beginPath();
        for (const s2 of i) t2.rect(Math.floor(e3 * r2), Math.round(s2.Pa * h2) - l2, o2, a2);
        t2.fill();
      })), t.useMediaCoordinateSpace((({ context: t2 }) => {
        t2.font = this.ev(), t2.fillStyle = s.textColor ?? this.Ml.textColor, t2.textAlign = this.jp ? "right" : "left", t2.textBaseline = "middle";
        const r2 = this.jp ? Math.round(e3 - n.B) : Math.round(e3 + n.C + n.B), h2 = i.map(((i2) => this.Fp.Di(t2, i2.Za)));
        for (let s2 = i.length; s2--; ) {
          const n2 = i[s2];
          t2.fillText(n2.Za, r2, n2.Pa + h2[s2]);
        }
      }));
    }
    ov() {
      if (null === this.Op || null === this.Yi) return;
      let t = this.Op.height / 2;
      const i = [], s = this.Yi.Dt().slice(), n = this.Pt.ap(), e3 = this.sv();
      this.Yi === n.$n() && this.Pt.ap().Dt().forEach(((t2) => {
        n.Un(t2) && s.push(t2);
      }));
      const r2 = this.Yi.Ma()[0], h2 = this.Yi;
      s.forEach(((s2) => {
        const e4 = s2.Ws(n, h2);
        e4.forEach(((t2) => {
          t2.Wi(null), t2.Hi() && i.push(t2);
        })), r2 === s2 && e4.length > 0 && (t = e4[0].Ii());
      })), i.forEach(((t2) => t2.Wi(t2.Ii())));
      this.Yi.N().alignLabels && this.mv(i, e3, t);
    }
    mv(t, i, s) {
      if (null === this.Op) return;
      const n = t.filter(((t2) => t2.Ii() <= s)), e3 = t.filter(((t2) => t2.Ii() > s));
      n.sort(((t2, i2) => i2.Ii() - t2.Ii())), n.length && e3.length && e3.push(n[0]), e3.sort(((t2, i2) => t2.Ii() - i2.Ii()));
      for (const s2 of t) {
        const t2 = Math.floor(s2.$t(i) / 2), n2 = s2.Ii();
        n2 > -t2 && n2 < t2 && s2.Wi(t2), n2 > this.Op.height - t2 && n2 < this.Op.height + t2 && s2.Wi(this.Op.height - t2);
      }
      ks(n, 1, this.Op.height, i), ks(e3, -1, this.Op.height, i);
    }
    fv(t) {
      if (null === this.Op) return;
      const i = this.rv(), s = this.sv(), n = this.jp ? "right" : "left";
      i.forEach(((i2) => {
        if (i2.Ui()) {
          i2.Tt(u(this.Yi)).nt(t, s, this.Fp, n);
        }
      }));
    }
    pv(t) {
      if (null === this.Op || null === this.Yi) return;
      const i = this.Pt.qp().Qt(), s = [], n = this.Pt.ap(), e3 = i.uc().Ws(n, this.Yi);
      e3.length && s.push(e3);
      const r2 = this.sv(), h2 = this.jp ? "right" : "left";
      s.forEach(((i2) => {
        i2.forEach(((i3) => {
          i3.Tt(u(this.Yi)).nt(t, r2, this.Fp, h2);
        }));
      }));
    }
    vv(t) {
      this.jf.style.cursor = 1 === t ? "ns-resize" : "default";
    }
    _l() {
      const t = this.nv();
      this.Hp < t && this.Pt.qp().Qt().Ih(), this.Hp = t;
    }
    ev() {
      return x(this.Ml.fontSize, this.Ml.fontFamily);
    }
  };
  function Rs(t, i) {
    return t.Jh?.(i) ?? [];
  }
  function Ds(t, i) {
    return t.Fs?.(i) ?? [];
  }
  function Vs(t, i) {
    return t.us?.(i) ?? [];
  }
  function Bs(t, i) {
    return t.Xh?.(i) ?? [];
  }
  var Is = class _Is {
    constructor(i, s) {
      this.Op = size({ width: 0, height: 0 }), this.wv = null, this.gv = null, this.Mv = null, this.bv = null, this.Sv = false, this.xv = new d(), this.Cv = new d(), this.Pv = 0, this.yv = false, this.kv = null, this.Tv = false, this.Rv = null, this.Dv = null, this.Up = false, this.$p = () => {
        this.Up || null === this.Vv || this.ts().ar();
      }, this.Yp = () => {
        this.Up || null === this.Vv || this.ts().ar();
      }, this.Vp = i, this.Vv = s, this.Vv.t_().i(this.Bv.bind(this), this, true), this.Iv = document.createElement("td"), this.Iv.style.padding = "0", this.Iv.style.position = "relative";
      const n = document.createElement("div");
      n.style.width = "100%", n.style.height = "100%", n.style.position = "relative", n.style.overflow = "hidden", this.Ev = document.createElement("td"), this.Ev.style.padding = "0", this.Av = document.createElement("td"), this.Av.style.padding = "0", this.Iv.appendChild(n), this.Gp = bs(n, size({ width: 16, height: 16 })), this.Gp.subscribeSuggestedBitmapSizeChanged(this.$p);
      const e3 = this.Gp.canvasElement;
      e3.style.position = "absolute", e3.style.zIndex = "1", e3.style.left = "0", e3.style.top = "0", this.Jp = bs(n, size({ width: 16, height: 16 })), this.Jp.subscribeSuggestedBitmapSizeChanged(this.Yp);
      const r2 = this.Jp.canvasElement;
      r2.style.position = "absolute", r2.style.zIndex = "2", r2.style.left = "0", r2.style.top = "0", this.Yf = document.createElement("tr"), this.Yf.appendChild(this.Ev), this.Yf.appendChild(this.Iv), this.Yf.appendChild(this.Av), this.zv(), this.Nf = new _s(this.Jp.canvasElement, this, { af: () => null === this.kv && !this.Vp.N().handleScroll.vertTouchDrag, lf: () => null === this.kv && !this.Vp.N().handleScroll.horzTouchDrag });
    }
    m() {
      null !== this.wv && this.wv.m(), null !== this.gv && this.gv.m(), this.Mv = null, this.Jp.unsubscribeSuggestedBitmapSizeChanged(this.Yp), Ss(this.Jp.canvasElement), this.Jp.dispose(), this.Gp.unsubscribeSuggestedBitmapSizeChanged(this.$p), Ss(this.Gp.canvasElement), this.Gp.dispose(), null !== this.Vv && (this.Vv.t_().u(this), this.Vv.m()), this.Nf.m();
    }
    ap() {
      return u(this.Vv);
    }
    Lv(t) {
      null !== this.Vv && this.Vv.t_().u(this), this.Vv = t, null !== this.Vv && this.Vv.t_().i(_Is.prototype.Bv.bind(this), this, true), this.zv(), this.Vp.$f().indexOf(this) === this.Vp.$f().length - 1 ? (this.Mv = this.Mv ?? new Ms(this.Iv, this.Vp), this.Mv.yt()) : (this.Mv?.Ip(), this.Mv = null);
    }
    qp() {
      return this.Vp;
    }
    Zf() {
      return this.Yf;
    }
    zv() {
      if (null !== this.Vv && (this.Ov(), 0 !== this.ts().js().length)) {
        if (null !== this.wv) {
          const t = this.Vv.Wo();
          this.wv._s(u(t));
        }
        if (null !== this.gv) {
          const t = this.Vv.Ho();
          this.gv._s(u(t));
        }
      }
    }
    Nv() {
      null !== this.wv && this.wv.yt(), null !== this.gv && this.gv.yt();
    }
    Bo() {
      return null !== this.Vv ? this.Vv.Bo() : 0;
    }
    Io(t) {
      this.Vv && this.Vv.Io(t);
    }
    sf(t) {
      if (!this.Vv) return;
      this.Fv();
      const i = t.localX, s = t.localY;
      this.Wv(i, s, t);
    }
    Sf(t) {
      this.Fv(), this.Hv(), this.Wv(t.localX, t.localY, t);
    }
    nf(t) {
      if (!this.Vv) return;
      this.Fv();
      const i = t.localX, s = t.localY;
      this.Wv(i, s, t);
    }
    mf(t) {
      null !== this.Vv && (this.Fv(), this.Uv(t));
    }
    Xd(t) {
      null !== this.Vv && this.$v(this.Cv, t);
    }
    qd(t) {
      this.Xd(t);
    }
    cf(t) {
      this.Fv(), this.qv(t), this.Wv(t.localX, t.localY, t);
    }
    vf(t) {
      null !== this.Vv && (this.Fv(), this.yv = false, this.Yv(t));
    }
    pf(t) {
      null !== this.Vv && this.Uv(t);
    }
    If(t) {
      if (this.yv = true, null === this.kv) {
        const i = { x: t.localX, y: t.localY };
        this.jv(i, i, t);
      }
    }
    Bf(t) {
      null !== this.Vv && (this.Fv(), this.Vv.Qt().lc(null), this.Kv());
    }
    Xv() {
      return this.xv;
    }
    Zv() {
      return this.Cv;
    }
    yf() {
      this.Pv = 1, this.ts().hn();
    }
    kf(t, i) {
      if (!this.Vp.N().handleScale.pinch) return;
      const s = 5 * (i - this.Pv);
      this.Pv = i, this.ts().bc(t._t, s);
    }
    Mf(t) {
      this.yv = false, this.Tv = null !== this.kv, this.Hv();
      const i = this.ts().uc();
      null !== this.kv && i.Vt() && (this.Rv = { x: i.si(), y: i.ni() }, this.kv = { x: t.localX, y: t.localY });
    }
    _f(t) {
      if (null === this.Vv) return;
      const i = t.localX, s = t.localY;
      if (null === this.kv) this.qv(t);
      else {
        this.Tv = false;
        const n = u(this.Rv), e3 = n.x + (i - this.kv.x), r2 = n.y + (s - this.kv.y);
        this.Wv(e3, r2, t);
      }
    }
    ff(t) {
      0 === this.qp().N().trackingMode.exitMode && (this.Tv = true), this.Gv(), this.Yv(t);
    }
    jn(t, i) {
      const s = this.Vv;
      return null === s ? null : yi(s, t, i);
    }
    Jv(i, s) {
      u("left" === s ? this.wv : this.gv).hv(size({ width: i, height: this.Op.height }));
    }
    Gf() {
      return this.Op;
    }
    hv(t) {
      equalSizes(this.Op, t) || (this.Op = t, this.Up = true, this.Gp.resizeCanvasElement(t), this.Jp.resizeCanvasElement(t), this.Up = false, this.Iv.style.width = t.width + "px", this.Iv.style.height = t.height + "px");
    }
    Qv() {
      const t = u(this.Vv);
      t.Fo(t.Wo()), t.Fo(t.Ho());
      for (const i of t.Ma()) if (t.Un(i)) {
        const s = i.Ft();
        null !== s && t.Fo(s), i.Ns();
      }
      for (const i of t.s_()) i.Ns();
    }
    Jf() {
      return this.Gp.bitmapSize;
    }
    Qf(t, i, s, n) {
      const e3 = this.Jf();
      if (e3.width > 0 && e3.height > 0 && (t.drawImage(this.Gp.canvasElement, i, s), n)) {
        const n2 = this.Jp.canvasElement;
        null !== t && t.drawImage(n2, i, s);
      }
    }
    lv(t) {
      if (0 === t) return;
      if (null === this.Vv) return;
      t > 1 && this.Qv(), null !== this.wv && this.wv.lv(t), null !== this.gv && this.gv.lv(t);
      const i = { colorSpace: this.Vp.N().layout.colorSpace };
      if (1 !== t) {
        this.Gp.applySuggestedBitmapSize();
        const t2 = tryCreateCanvasRenderingTarget2D(this.Gp, i);
        null !== t2 && (t2.useBitmapCoordinateSpace(((t3) => {
          this._v(t3);
        })), this.Vv && (this.tm(t2, Rs), this.im(t2), this.tm(t2, Ds), this.tm(t2, Vs)));
      }
      this.Jp.applySuggestedBitmapSize();
      const s = tryCreateCanvasRenderingTarget2D(this.Jp, i);
      null !== s && (s.useBitmapCoordinateSpace((({ context: t2, bitmapSize: i2 }) => {
        t2.clearRect(0, 0, i2.width, i2.height);
      })), this.sm(s), this.tm(s, Bs), this.tm(s, Vs));
    }
    nm() {
      return this.wv;
    }
    rm() {
      return this.gv;
    }
    cv(t, i) {
      this.tm(t, i);
    }
    Bv() {
      null !== this.Vv && this.Vv.t_().u(this), this.Vv = null;
    }
    Uv(t) {
      this.$v(this.xv, t);
    }
    $v(t, i) {
      const s = i.localX, n = i.localY;
      t.v() && t.p(this.ts().Et().cu(s), { x: s, y: n }, i);
    }
    _v({ context: t, bitmapSize: i }) {
      const { width: s, height: n } = i, e3 = this.ts(), r2 = e3.$(), h2 = e3.Wc();
      r2 === h2 ? L(t, 0, 0, s, n, h2) : F(t, 0, 0, s, n, r2, h2);
    }
    im(t) {
      const i = u(this.Vv), s = i.i_().lr().Tt(i);
      null !== s && s.nt(t, false);
    }
    sm(t) {
      this.hm(t, Ds, Cs, this.ts().uc());
    }
    tm(t, i) {
      const s = u(this.Vv), n = s.Dt(), e3 = s.s_();
      for (const s2 of e3) this.hm(t, i, xs, s2);
      for (const s2 of n) this.hm(t, i, xs, s2);
      for (const s2 of e3) this.hm(t, i, Cs, s2);
      for (const s2 of n) this.hm(t, i, Cs, s2);
    }
    hm(t, i, s, n) {
      const e3 = u(this.Vv), r2 = e3.Qt().ac(), h2 = null !== r2 && r2.n_ === n, a2 = null !== r2 && h2 && void 0 !== r2.e_ ? r2.e_.Xn : void 0;
      Ps(i, ((i2) => s(i2, t, h2, a2)), n, e3);
    }
    Ov() {
      if (null === this.Vv) return;
      const t = this.Vp, i = this.Vv.Wo().N().visible, s = this.Vv.Ho().N().visible;
      i || null === this.wv || (this.Ev.removeChild(this.wv.Zf()), this.wv.m(), this.wv = null), s || null === this.gv || (this.Av.removeChild(this.gv.Zf()), this.gv.m(), this.gv = null);
      const n = t.Qt().Bc();
      i && null === this.wv && (this.wv = new Ts(this, t.N(), n, "left"), this.Ev.appendChild(this.wv.Zf())), s && null === this.gv && (this.gv = new Ts(this, t.N(), n, "right"), this.Av.appendChild(this.gv.Zf()));
    }
    am(t) {
      return t.Ef && this.yv || null !== this.kv;
    }
    lm(t) {
      return Math.max(0, Math.min(t, this.Op.width - 1));
    }
    om(t) {
      return Math.max(0, Math.min(t, this.Op.height - 1));
    }
    Wv(t, i, s) {
      this.ts().Tc(this.lm(t), this.om(i), s, u(this.Vv));
    }
    Kv() {
      this.ts().Dc();
    }
    Gv() {
      this.Tv && (this.kv = null, this.Kv());
    }
    jv(t, i, s) {
      this.kv = t, this.Tv = false, this.Wv(i.x, i.y, s);
      const n = this.ts().uc();
      this.Rv = { x: n.si(), y: n.ni() };
    }
    ts() {
      return this.Vp.Qt();
    }
    Yv(t) {
      if (!this.Sv) return;
      const i = this.ts(), s = this.ap();
      if (i.Ko(s, s.ks()), this.bv = null, this.Sv = false, i.Pc(), null !== this.Dv) {
        const t2 = performance.now(), s2 = i.Et();
        this.Dv.le(s2.gu(), t2), this.Dv.Ru(t2) || i._n(this.Dv);
      }
    }
    Fv() {
      this.kv = null;
    }
    Hv() {
      if (!this.Vv) return;
      if (this.ts().hn(), document.activeElement !== document.body && document.activeElement !== document.documentElement) u(document.activeElement).blur();
      else {
        const t = document.getSelection();
        null !== t && t.removeAllRanges();
      }
      !this.Vv.ks().Ki() && this.ts().Et().Ki();
    }
    qv(t) {
      if (null === this.Vv) return;
      const i = this.ts(), s = i.Et();
      if (s.Ki()) return;
      const n = this.Vp.N(), e3 = n.handleScroll, r2 = n.kineticScroll;
      if ((!e3.pressedMouseMove || t.Ef) && (!e3.horzTouchDrag && !e3.vertTouchDrag || !t.Ef)) return;
      const h2 = this.Vv.ks(), a2 = performance.now();
      if (null !== this.bv || this.am(t) || (this.bv = { x: t.clientX, y: t.clientY, rd: a2, _m: t.localX, um: t.localY }), null !== this.bv && !this.Sv && (this.bv.x !== t.clientX || this.bv.y !== t.clientY)) {
        if (t.Ef && r2.touch || !t.Ef && r2.mouse) {
          const t2 = s.mu();
          this.Dv = new gs(0.2 / t2, 7 / t2, 0.997, 15 / t2), this.Dv.Pp(s.gu(), this.bv.rd);
        } else this.Dv = null;
        h2.Ki() || i.Yo(this.Vv, h2, t.localY), i.xc(t.localX), this.Sv = true;
      }
      this.Sv && (h2.Ki() || i.jo(this.Vv, h2, t.localY), i.Cc(t.localX), null !== this.Dv && this.Dv.Pp(s.gu(), a2));
    }
  };
  var Es = class {
    constructor(i, s, n, e3, r2) {
      this.xt = true, this.Op = size({ width: 0, height: 0 }), this.$p = () => this.lv(3), this.jp = "left" === i, this.Ju = n.Bc, this.Ps = s, this.dm = e3, this.fm = r2, this.jf = document.createElement("div"), this.jf.style.width = "25px", this.jf.style.height = "100%", this.jf.style.overflow = "hidden", this.Gp = bs(this.jf, size({ width: 16, height: 16 })), this.Gp.subscribeSuggestedBitmapSizeChanged(this.$p);
    }
    m() {
      this.Gp.unsubscribeSuggestedBitmapSizeChanged(this.$p), Ss(this.Gp.canvasElement), this.Gp.dispose();
    }
    Zf() {
      return this.jf;
    }
    Gf() {
      return this.Op;
    }
    hv(t) {
      equalSizes(this.Op, t) || (this.Op = t, this.Gp.resizeCanvasElement(t), this.jf.style.width = `${t.width}px`, this.jf.style.height = `${t.height}px`, this.xt = true);
    }
    lv(t) {
      if (t < 3 && !this.xt) return;
      if (0 === this.Op.width || 0 === this.Op.height) return;
      this.xt = false, this.Gp.applySuggestedBitmapSize();
      const i = tryCreateCanvasRenderingTarget2D(this.Gp, { colorSpace: this.Ps.layout.colorSpace });
      null !== i && i.useBitmapCoordinateSpace(((t2) => {
        this._v(t2), this.uv(t2);
      }));
    }
    Jf() {
      return this.Gp.bitmapSize;
    }
    Qf(t, i, s) {
      const n = this.Jf();
      n.width > 0 && n.height > 0 && t.drawImage(this.Gp.canvasElement, i, s);
    }
    uv({ context: t, bitmapSize: i, horizontalPixelRatio: s, verticalPixelRatio: n }) {
      if (!this.dm()) return;
      t.fillStyle = this.Ps.timeScale.borderColor;
      const e3 = Math.floor(this.Ju.N().S * s), r2 = Math.floor(this.Ju.N().S * n), h2 = this.jp ? i.width - e3 : 0;
      t.fillRect(h2, 0, e3, r2);
    }
    _v({ context: t, bitmapSize: i }) {
      L(t, 0, 0, i.width, i.height, this.fm());
    }
  };
  function As(t) {
    return (i) => i.ia?.(t) ?? [];
  }
  var zs = As("normal");
  var Ls = As("top");
  var Os = As("bottom");
  var Ns = class {
    constructor(i, s) {
      this.pm = null, this.vm = null, this.M = null, this.wm = false, this.Op = size({ width: 0, height: 0 }), this.gm = new d(), this.Fp = new rt(5), this.Up = false, this.$p = () => {
        this.Up || this.Vp.Qt().ar();
      }, this.Yp = () => {
        this.Up || this.Vp.Qt().ar();
      }, this.Vp = i, this.o_ = s, this.Ps = i.N().layout, this.kp = document.createElement("tr"), this.Mm = document.createElement("td"), this.Mm.style.padding = "0", this.bm = document.createElement("td"), this.bm.style.padding = "0", this.jf = document.createElement("td"), this.jf.style.height = "25px", this.jf.style.padding = "0", this.Sm = document.createElement("div"), this.Sm.style.width = "100%", this.Sm.style.height = "100%", this.Sm.style.position = "relative", this.Sm.style.overflow = "hidden", this.jf.appendChild(this.Sm), this.Gp = bs(this.Sm, size({ width: 16, height: 16 })), this.Gp.subscribeSuggestedBitmapSizeChanged(this.$p);
      const n = this.Gp.canvasElement;
      n.style.position = "absolute", n.style.zIndex = "1", n.style.left = "0", n.style.top = "0", this.Jp = bs(this.Sm, size({ width: 16, height: 16 })), this.Jp.subscribeSuggestedBitmapSizeChanged(this.Yp);
      const e3 = this.Jp.canvasElement;
      e3.style.position = "absolute", e3.style.zIndex = "2", e3.style.left = "0", e3.style.top = "0", this.kp.appendChild(this.Mm), this.kp.appendChild(this.jf), this.kp.appendChild(this.bm), this.xm(), this.Vp.Qt().Vo().i(this.xm.bind(this), this), this.Nf = new _s(this.Jp.canvasElement, this, { af: () => true, lf: () => !this.Vp.N().handleScroll.horzTouchDrag });
    }
    m() {
      this.Nf.m(), null !== this.pm && this.pm.m(), null !== this.vm && this.vm.m(), this.Jp.unsubscribeSuggestedBitmapSizeChanged(this.Yp), Ss(this.Jp.canvasElement), this.Jp.dispose(), this.Gp.unsubscribeSuggestedBitmapSizeChanged(this.$p), Ss(this.Gp.canvasElement), this.Gp.dispose();
    }
    Zf() {
      return this.kp;
    }
    Cm() {
      return this.pm;
    }
    Pm() {
      return this.vm;
    }
    Sf(t) {
      if (this.wm) return;
      this.wm = true;
      const i = this.Vp.Qt();
      !i.Et().Ki() && this.Vp.N().handleScale.axisPressedMouseMove.time && i.Mc(t.localX);
    }
    Mf(t) {
      this.Sf(t);
    }
    xf() {
      const t = this.Vp.Qt();
      !t.Et().Ki() && this.wm && (this.wm = false, this.Vp.N().handleScale.axisPressedMouseMove.time && t.kc());
    }
    cf(t) {
      const i = this.Vp.Qt();
      !i.Et().Ki() && this.Vp.N().handleScale.axisPressedMouseMove.time && i.yc(t.localX);
    }
    _f(t) {
      this.cf(t);
    }
    vf() {
      this.wm = false;
      const t = this.Vp.Qt();
      t.Et().Ki() && !this.Vp.N().handleScale.axisPressedMouseMove.time || t.kc();
    }
    ff() {
      this.vf();
    }
    Xd() {
      this.Vp.N().handleScale.axisDoubleClickReset.time && this.Vp.Qt().cn();
    }
    qd() {
      this.Xd();
    }
    sf() {
      this.Vp.Qt().N().handleScale.axisPressedMouseMove.time && this.vv(1);
    }
    Bf() {
      this.vv(0);
    }
    Gf() {
      return this.Op;
    }
    ym() {
      return this.gm;
    }
    km(i, n, e3) {
      equalSizes(this.Op, i) || (this.Op = i, this.Up = true, this.Gp.resizeCanvasElement(i), this.Jp.resizeCanvasElement(i), this.Up = false, this.jf.style.width = `${i.width}px`, this.jf.style.height = `${i.height}px`, this.gm.p(i)), null !== this.pm && this.pm.hv(size({ width: n, height: i.height })), null !== this.vm && this.vm.hv(size({ width: e3, height: i.height }));
    }
    Tm() {
      const t = this.Rm();
      return Math.ceil(t.S + t.C + t.P + t.A + t.V + t.Dm);
    }
    yt() {
      this.Vp.Qt().Et().Da();
    }
    Jf() {
      return this.Gp.bitmapSize;
    }
    Qf(t, i, s, n) {
      const e3 = this.Jf();
      if (e3.width > 0 && e3.height > 0 && (t.drawImage(this.Gp.canvasElement, i, s), n)) {
        const n2 = this.Jp.canvasElement;
        t.drawImage(n2, i, s);
      }
    }
    lv(t) {
      if (0 === t) return;
      const i = { colorSpace: this.Ps.colorSpace };
      if (1 !== t) {
        this.Gp.applySuggestedBitmapSize();
        const s2 = tryCreateCanvasRenderingTarget2D(this.Gp, i);
        null !== s2 && (s2.useBitmapCoordinateSpace(((t2) => {
          this._v(t2), this.uv(t2), this.Vm(s2, Os);
        })), this.dv(s2), this.Vm(s2, zs)), null !== this.pm && this.pm.lv(t), null !== this.vm && this.vm.lv(t);
      }
      this.Jp.applySuggestedBitmapSize();
      const s = tryCreateCanvasRenderingTarget2D(this.Jp, i);
      null !== s && (s.useBitmapCoordinateSpace((({ context: t2, bitmapSize: i2 }) => {
        t2.clearRect(0, 0, i2.width, i2.height);
      })), this.Bm([...this.Vp.Qt().js(), this.Vp.Qt().uc()], s), this.Vm(s, Ls));
    }
    Vm(t, i) {
      const s = this.Vp.Qt().js();
      for (const n of s) Ps(i, ((i2) => xs(i2, t, false, void 0)), n, void 0);
      for (const n of s) Ps(i, ((i2) => Cs(i2, t, false, void 0)), n, void 0);
    }
    _v({ context: t, bitmapSize: i }) {
      L(t, 0, 0, i.width, i.height, this.Vp.Qt().Wc());
    }
    uv({ context: t, bitmapSize: i, verticalPixelRatio: s }) {
      if (this.Vp.N().timeScale.borderVisible) {
        t.fillStyle = this.Im();
        const n = Math.max(1, Math.floor(this.Rm().S * s));
        t.fillRect(0, 0, i.width, n);
      }
    }
    dv(t) {
      const i = this.Vp.Qt().Et(), s = i.Da();
      if (!s || 0 === s.length) return;
      const n = this.o_.maxTickMarkWeight(s), e3 = this.Rm(), r2 = i.N();
      r2.borderVisible && r2.ticksVisible && t.useBitmapCoordinateSpace((({ context: t2, horizontalPixelRatio: i2, verticalPixelRatio: n2 }) => {
        t2.strokeStyle = this.Im(), t2.fillStyle = this.Im();
        const r3 = Math.max(1, Math.floor(i2)), h2 = Math.floor(0.5 * i2);
        t2.beginPath();
        const a2 = Math.round(e3.C * n2);
        for (let n3 = s.length; n3--; ) {
          const e4 = Math.round(s[n3].coord * i2);
          t2.rect(e4 - h2, 0, r3, a2);
        }
        t2.fill();
      })), t.useMediaCoordinateSpace((({ context: t2 }) => {
        const i2 = e3.S + e3.C + e3.A + e3.P / 2;
        t2.textAlign = "center", t2.textBaseline = "middle", t2.fillStyle = this.H(), t2.font = this.ev();
        for (const e4 of s) if (e4.weight < n) {
          const s2 = e4.needAlignCoordinate ? this.Em(t2, e4.coord, e4.label) : e4.coord;
          t2.fillText(e4.label, s2, i2);
        }
        this.Vp.N().timeScale.allowBoldLabels && (t2.font = this.Am());
        for (const e4 of s) if (e4.weight >= n) {
          const s2 = e4.needAlignCoordinate ? this.Em(t2, e4.coord, e4.label) : e4.coord;
          t2.fillText(e4.label, s2, i2);
        }
      }));
    }
    Em(t, i, s) {
      const n = this.Fp.Vi(t, s), e3 = n / 2, r2 = Math.floor(i - e3) + 0.5;
      return r2 < 0 ? i += Math.abs(0 - r2) : r2 + n > this.Op.width && (i -= Math.abs(this.Op.width - (r2 + n))), i;
    }
    Bm(t, i) {
      const s = this.Rm();
      for (const n of t) for (const t2 of n.cs()) t2.Tt().nt(i, s);
    }
    Im() {
      return this.Vp.N().timeScale.borderColor;
    }
    H() {
      return this.Ps.textColor;
    }
    F() {
      return this.Ps.fontSize;
    }
    ev() {
      return x(this.F(), this.Ps.fontFamily);
    }
    Am() {
      return x(this.F(), this.Ps.fontFamily, "bold");
    }
    Rm() {
      null === this.M && (this.M = { S: 1, L: NaN, A: NaN, V: NaN, Ji: NaN, C: 5, P: NaN, k: "", Gi: new rt(), Dm: 0 });
      const t = this.M, i = this.ev();
      if (t.k !== i) {
        const s = this.F();
        t.P = s, t.k = i, t.A = 3 * s / 12, t.V = 3 * s / 12, t.Ji = 9 * s / 12, t.L = 0, t.Dm = 4 * s / 12, t.Gi.Bn();
      }
      return this.M;
    }
    vv(t) {
      this.jf.style.cursor = 1 === t ? "ew-resize" : "default";
    }
    xm() {
      const t = this.Vp.Qt(), i = t.N();
      i.leftPriceScale.visible || null === this.pm || (this.Mm.removeChild(this.pm.Zf()), this.pm.m(), this.pm = null), i.rightPriceScale.visible || null === this.vm || (this.bm.removeChild(this.vm.Zf()), this.vm.m(), this.vm = null);
      const s = { Bc: this.Vp.Qt().Bc() }, n = () => i.leftPriceScale.borderVisible && t.Et().N().borderVisible, e3 = () => t.Wc();
      i.leftPriceScale.visible && null === this.pm && (this.pm = new Es("left", i, s, n, e3), this.Mm.appendChild(this.pm.Zf())), i.rightPriceScale.visible && null === this.vm && (this.vm = new Es("right", i, s, n, e3), this.bm.appendChild(this.vm.Zf()));
    }
  };
  var Fs = !!rs && !!navigator.userAgentData && navigator.userAgentData.brands.some(((t) => t.brand.includes("Chromium"))) && !!rs && (navigator?.userAgentData?.platform ? "Windows" === navigator.userAgentData.platform : navigator.userAgent.toLowerCase().indexOf("win") >= 0);
  var Ws = class {
    constructor(t, i, s) {
      var n;
      this.zm = [], this.Lm = [], this.Om = 0, this.il = 0, this.Mo = 0, this.Nm = 0, this.Fm = 0, this.Wm = null, this.Hm = false, this.xv = new d(), this.Cv = new d(), this.Xu = new d(), this.Um = null, this.$m = null, this.Dp = t, this.Ps = i, this.o_ = s, this.kp = document.createElement("div"), this.kp.classList.add("tv-lightweight-charts"), this.kp.style.overflow = "hidden", this.kp.style.direction = "ltr", this.kp.style.width = "100%", this.kp.style.height = "100%", (n = this.kp).style.userSelect = "none", n.style.webkitUserSelect = "none", n.style.msUserSelect = "none", n.style.MozUserSelect = "none", n.style.webkitTapHighlightColor = "transparent", this.qm = document.createElement("table"), this.qm.setAttribute("cellspacing", "0"), this.kp.appendChild(this.qm), this.Ym = this.jm.bind(this), Hs(this.Ps) && this.Km(true), this.ts = new Ni(this.Gu.bind(this), this.Ps, s), this.Qt().cc().i(this.Xm.bind(this), this), this.Zm = new Ns(this, this.o_), this.qm.appendChild(this.Zm.Zf());
      const e3 = i.autoSize && this.Gm();
      let r2 = this.Ps.width, h2 = this.Ps.height;
      if (e3 || 0 === r2 || 0 === h2) {
        const i2 = t.getBoundingClientRect();
        r2 = r2 || i2.width, h2 = h2 || i2.height;
      }
      this.Jm(r2, h2), this.Qm(), t.appendChild(this.kp), this.tw(), this.ts.Et().Iu().i(this.ts.Ih.bind(this.ts), this), this.ts.Vo().i(this.ts.Ih.bind(this.ts), this);
    }
    Qt() {
      return this.ts;
    }
    N() {
      return this.Ps;
    }
    $f() {
      return this.zm;
    }
    iw() {
      return this.Zm;
    }
    m() {
      this.Km(false), 0 !== this.Om && window.cancelAnimationFrame(this.Om), this.ts.cc().u(this), this.ts.Et().Iu().u(this), this.ts.Vo().u(this), this.ts.m();
      for (const t of this.zm) this.qm.removeChild(t.Zf()), t.Xv().u(this), t.Zv().u(this), t.m();
      this.zm = [];
      for (const t of this.Lm) this.sw(t);
      this.Lm = [], u(this.Zm).m(), null !== this.kp.parentElement && this.kp.parentElement.removeChild(this.kp), this.Xu.m(), this.xv.m(), this.Cv.m(), this.nw();
    }
    Jm(i, s, n = false) {
      if (this.il === s && this.Mo === i) return;
      const e3 = (function(i2) {
        const s2 = Math.floor(i2.width), n2 = Math.floor(i2.height);
        return size({ width: s2 - s2 % 2, height: n2 - n2 % 2 });
      })(size({ width: i, height: s }));
      this.il = e3.height, this.Mo = e3.width;
      const r2 = this.il + "px", h2 = this.Mo + "px";
      u(this.kp).style.height = r2, u(this.kp).style.width = h2, this.qm.style.height = r2, this.qm.style.width = h2, n ? this.ew(G.gn(), performance.now()) : this.ts.Ih();
    }
    lv(t) {
      void 0 === t && (t = G.gn());
      for (let i = 0; i < this.zm.length; i++) this.zm[i].lv(t.en(i).tn);
      this.Ps.timeScale.visible && this.Zm.lv(t.nn());
    }
    hr(t) {
      const i = Hs(this.Ps);
      this.ts.hr(t);
      const s = Hs(this.Ps);
      s !== i && this.Km(s), t.layout?.panes && this.rw(), this.tw(), this.hw(t);
    }
    Xv() {
      return this.xv;
    }
    Zv() {
      return this.Cv;
    }
    cc() {
      return this.Xu;
    }
    aw(t = false) {
      null !== this.Wm && (this.ew(this.Wm, performance.now()), this.Wm = null);
      const i = this.lw(null), s = document.createElement("canvas");
      s.width = i.width, s.height = i.height;
      const n = u(s.getContext("2d"));
      return this.lw(n, t), s;
    }
    ow(t) {
      if ("left" === t && !this._w()) return 0;
      if ("right" === t && !this.uw()) return 0;
      if (0 === this.zm.length) return 0;
      return u("left" === t ? this.zm[0].nm() : this.zm[0].rm()).av();
    }
    cw() {
      return this.Ps.autoSize && null !== this.Um;
    }
    ip() {
      return this.kp;
    }
    dw(t) {
      this.$m = t, this.$m ? this.ip().style.setProperty("cursor", t) : this.ip().style.removeProperty("cursor");
    }
    fw() {
      return this.$m;
    }
    pw(t) {
      return _(this.zm[t]).Gf();
    }
    rw() {
      this.Lm.forEach(((t) => {
        t.yt();
      }));
    }
    hw(t) {
      (void 0 !== t.autoSize || !this.Um || void 0 === t.width && void 0 === t.height) && (t.autoSize && !this.Um && this.Gm(), false === t.autoSize && null !== this.Um && this.nw(), t.autoSize || void 0 === t.width && void 0 === t.height || this.Jm(t.width || this.Mo, t.height || this.il));
    }
    lw(i, s) {
      let n = 0, e3 = 0;
      const r2 = this.zm[0], h2 = (t, n2) => {
        let e4 = 0;
        for (let r3 = 0; r3 < this.zm.length; r3++) {
          const h3 = this.zm[r3], a3 = u("left" === t ? h3.nm() : h3.rm()), l2 = a3.Jf();
          if (null !== i && a3.Qf(i, n2, e4, s), e4 += l2.height, r3 < this.zm.length - 1) {
            const t2 = this.Lm[r3], s2 = t2.Jf();
            null !== i && t2.Qf(i, n2, e4), e4 += s2.height;
          }
        }
      };
      if (this._w()) {
        h2("left", 0);
        n += u(r2.nm()).Jf().width;
      }
      for (let t = 0; t < this.zm.length; t++) {
        const r3 = this.zm[t], h3 = r3.Jf();
        if (null !== i && r3.Qf(i, n, e3, s), e3 += h3.height, t < this.zm.length - 1) {
          const s2 = this.Lm[t], r4 = s2.Jf();
          null !== i && s2.Qf(i, n, e3), e3 += r4.height;
        }
      }
      if (n += r2.Jf().width, this.uw()) {
        h2("right", n);
        n += u(r2.rm()).Jf().width;
      }
      const a2 = (t, s2, n2) => {
        u("left" === t ? this.Zm.Cm() : this.Zm.Pm()).Qf(u(i), s2, n2);
      };
      if (this.Ps.timeScale.visible) {
        const t = this.Zm.Jf();
        if (null !== i) {
          let n2 = 0;
          this._w() && (a2("left", n2, e3), n2 = u(r2.nm()).Jf().width), this.Zm.Qf(i, n2, e3, s), n2 += t.width, this.uw() && a2("right", n2, e3);
        }
        e3 += t.height;
      }
      return size({ width: n, height: e3 });
    }
    mw() {
      let i = 0, s = 0, n = 0;
      for (const t of this.zm) this._w() && (s = Math.max(s, u(t.nm()).nv(), this.Ps.leftPriceScale.minimumWidth)), this.uw() && (n = Math.max(n, u(t.rm()).nv(), this.Ps.rightPriceScale.minimumWidth)), i += t.Bo();
      s = ls(s), n = ls(n);
      const e3 = this.Mo, r2 = this.il, h2 = Math.max(e3 - s - n, 0), a2 = 1 * this.Lm.length, l2 = this.Ps.timeScale.visible;
      let o2 = l2 ? Math.max(this.Zm.Tm(), this.Ps.timeScale.minimumHeight) : 0;
      var _2;
      o2 = (_2 = o2) + _2 % 2;
      const c2 = a2 + o2, d2 = r2 < c2 ? 0 : r2 - c2, f2 = d2 / i;
      let p2 = 0;
      const v2 = window.devicePixelRatio || 1;
      for (let i2 = 0; i2 < this.zm.length; ++i2) {
        const e4 = this.zm[i2];
        e4.Lv(this.ts.$s()[i2]);
        let r3 = 0, a3 = 0;
        a3 = i2 === this.zm.length - 1 ? Math.ceil((d2 - p2) * v2) / v2 : Math.round(e4.Bo() * f2 * v2) / v2, r3 = Math.max(a3, 2), p2 += r3, e4.hv(size({ width: h2, height: r3 })), this._w() && e4.Jv(s, "left"), this.uw() && e4.Jv(n, "right"), e4.ap() && this.ts.dc(e4.ap(), r3);
      }
      this.Zm.km(size({ width: l2 ? h2 : 0, height: o2 }), l2 ? s : 0, l2 ? n : 0), this.ts.Eo(h2), this.Nm !== s && (this.Nm = s), this.Fm !== n && (this.Fm = n);
    }
    Km(t) {
      t ? this.kp.addEventListener("wheel", this.Ym, { passive: false }) : this.kp.removeEventListener("wheel", this.Ym);
    }
    ww(t) {
      switch (t.deltaMode) {
        case t.DOM_DELTA_PAGE:
          return 120;
        case t.DOM_DELTA_LINE:
          return 32;
      }
      return Fs ? 1 / window.devicePixelRatio : 1;
    }
    jm(t) {
      if (!(0 !== t.deltaX && this.Ps.handleScroll.mouseWheel || 0 !== t.deltaY && this.Ps.handleScale.mouseWheel)) return;
      const i = this.ww(t), s = i * t.deltaX / 100, n = -i * t.deltaY / 100;
      if (t.cancelable && t.preventDefault(), 0 !== n && this.Ps.handleScale.mouseWheel) {
        const i2 = Math.sign(n) * Math.min(1, Math.abs(n)), s2 = t.clientX - this.kp.getBoundingClientRect().left;
        this.Qt().bc(s2, i2);
      }
      0 !== s && this.Ps.handleScroll.mouseWheel && this.Qt().Sc(-80 * s);
    }
    ew(t, i) {
      const s = t.nn();
      3 === s && this.gw(), 3 !== s && 2 !== s || (this.Mw(t), this.bw(t, i), this.Zm.yt(), this.zm.forEach(((t2) => {
        t2.Nv();
      })), 3 === this.Wm?.nn() && (this.Wm.vn(t), this.gw(), this.Mw(this.Wm), this.bw(this.Wm, i), t = this.Wm, this.Wm = null)), this.lv(t);
    }
    bw(t, i) {
      for (const s of t.pn()) this.mn(s, i);
    }
    Mw(t) {
      const i = this.ts.$s();
      for (let s = 0; s < i.length; s++) t.en(s).sn && i[s].Go();
    }
    mn(t, i) {
      const s = this.ts.Et();
      switch (t.an) {
        case 0:
          s.Au();
          break;
        case 1:
          s.zu(t.Wt);
          break;
        case 2:
          s.dn(t.Wt);
          break;
        case 3:
          s.fn(t.Wt);
          break;
        case 4:
          s.Su();
          break;
        case 5:
          t.Wt.Ru(i) || s.fn(t.Wt.Du(i));
      }
    }
    Gu(t) {
      null !== this.Wm ? this.Wm.vn(t) : this.Wm = t, this.Hm || (this.Hm = true, this.Om = window.requestAnimationFrame(((t2) => {
        if (this.Hm = false, this.Om = 0, null !== this.Wm) {
          const i = this.Wm;
          this.Wm = null, this.ew(i, t2);
          for (const s of i.pn()) if (5 === s.an && !s.Wt.Ru(t2)) {
            this.Qt()._n(s.Wt);
            break;
          }
        }
      })));
    }
    gw() {
      this.Qm();
    }
    sw(t) {
      this.qm.removeChild(t.Zf()), t.m();
    }
    Qm() {
      const t = this.ts.$s(), i = t.length, s = this.zm.length;
      for (let t2 = i; t2 < s; t2++) {
        const t3 = _(this.zm.pop());
        this.qm.removeChild(t3.Zf()), t3.Xv().u(this), t3.Zv().u(this), t3.m();
        const i2 = this.Lm.pop();
        void 0 !== i2 && this.sw(i2);
      }
      for (let n = s; n < i; n++) {
        const i2 = new Is(this, t[n]);
        if (i2.Xv().i(this.Sw.bind(this, i2), this), i2.Zv().i(this.xw.bind(this, i2), this), this.zm.push(i2), n > 0) {
          const t2 = new vs(this, n - 1, n);
          this.Lm.push(t2), this.qm.insertBefore(t2.Zf(), this.Zm.Zf());
        }
        this.qm.insertBefore(i2.Zf(), this.Zm.Zf());
      }
      for (let s2 = 0; s2 < i; s2++) {
        const i2 = t[s2], n = this.zm[s2];
        n.ap() !== i2 ? n.Lv(i2) : n.zv();
      }
      this.tw(), this.mw();
    }
    Cw(t, i, s, n) {
      const e3 = /* @__PURE__ */ new Map();
      if (null !== t) {
        this.ts.js().forEach(((i2) => {
          const s2 = i2.Xs().Fr(t);
          null !== s2 && e3.set(i2, s2);
        }));
      }
      let r2;
      if (null !== t) {
        const i2 = this.ts.Et().ss(t)?.originalTime;
        void 0 !== i2 && (r2 = i2);
      }
      const h2 = this.Qt().ac(), a2 = null !== h2 && h2.n_ instanceof Kt ? h2.n_ : void 0, l2 = null !== h2 && void 0 !== h2.e_ ? h2.e_.Kn : void 0, o2 = this.Pw(n);
      return { yw: r2, Re: t ?? void 0, kw: i ?? void 0, Tw: -1 !== o2 ? o2 : void 0, Rw: a2, Dw: e3, Vw: l2, Bw: s ?? void 0 };
    }
    Pw(t) {
      let i = -1;
      if (t) i = this.zm.indexOf(t);
      else {
        const t2 = this.Qt().uc().Us();
        null !== t2 && (i = this.Qt().$s().indexOf(t2));
      }
      return i;
    }
    Sw(t, i, s, n) {
      this.xv.p((() => this.Cw(i, s, n, t)));
    }
    xw(t, i, s, n) {
      this.Cv.p((() => this.Cw(i, s, n, t)));
    }
    Xm(t, i, s) {
      this.dw(this.Qt().ac()?.h_ ?? null), this.Xu.p((() => this.Cw(t, i, s)));
    }
    tw() {
      const t = this.Ps.timeScale.visible ? "" : "none";
      this.Zm.Zf().style.display = t;
    }
    _w() {
      return this.zm[0].ap().Wo().N().visible;
    }
    uw() {
      return this.zm[0].ap().Ho().N().visible;
    }
    Gm() {
      return "ResizeObserver" in window && (this.Um = new ResizeObserver(((t) => {
        const i = t[t.length - 1];
        i && this.Jm(i.contentRect.width, i.contentRect.height);
      })), this.Um.observe(this.Dp, { box: "border-box" }), true);
    }
    nw() {
      null !== this.Um && this.Um.disconnect(), this.Um = null;
    }
  };
  function Hs(t) {
    return Boolean(t.handleScroll.mouseWheel || t.handleScale.mouseWheel);
  }
  function Us(t) {
    return void 0 === t.open && void 0 === t.value;
  }
  function $s(t) {
    return (function(t2) {
      return void 0 !== t2.open;
    })(t) || (function(t2) {
      return void 0 !== t2.value;
    })(t);
  }
  function qs(t, i, s, n) {
    const e3 = s.value, r2 = { Re: i, wt: t, Wt: [e3, e3, e3, e3], yw: n };
    return void 0 !== s.color && (r2.R = s.color), r2;
  }
  function Ys(t, i, s, n) {
    const e3 = s.value, r2 = { Re: i, wt: t, Wt: [e3, e3, e3, e3], yw: n };
    return void 0 !== s.lineColor && (r2.vt = s.lineColor), void 0 !== s.topColor && (r2.mr = s.topColor), void 0 !== s.bottomColor && (r2.wr = s.bottomColor), r2;
  }
  function js(t, i, s, n) {
    const e3 = s.value, r2 = { Re: i, wt: t, Wt: [e3, e3, e3, e3], yw: n };
    return void 0 !== s.topLineColor && (r2.gr = s.topLineColor), void 0 !== s.bottomLineColor && (r2.Mr = s.bottomLineColor), void 0 !== s.topFillColor1 && (r2.br = s.topFillColor1), void 0 !== s.topFillColor2 && (r2.Sr = s.topFillColor2), void 0 !== s.bottomFillColor1 && (r2.Cr = s.bottomFillColor1), void 0 !== s.bottomFillColor2 && (r2.Pr = s.bottomFillColor2), r2;
  }
  function Ks(t, i, s, n) {
    const e3 = { Re: i, wt: t, Wt: [s.open, s.high, s.low, s.close], yw: n };
    return void 0 !== s.color && (e3.R = s.color), e3;
  }
  function Xs(t, i, s, n) {
    const e3 = { Re: i, wt: t, Wt: [s.open, s.high, s.low, s.close], yw: n };
    return void 0 !== s.color && (e3.R = s.color), void 0 !== s.borderColor && (e3.Ht = s.borderColor), void 0 !== s.wickColor && (e3.vr = s.wickColor), e3;
  }
  function Zs(t, i, s, n, e3) {
    const r2 = _(e3)(s), h2 = Math.max(...r2), a2 = Math.min(...r2), l2 = r2[r2.length - 1], o2 = [l2, h2, a2, l2], { time: u2, color: c2, ...d2 } = s;
    return { Re: i, wt: t, Wt: o2, yw: n, se: d2, R: c2 };
  }
  function Gs(t) {
    return void 0 !== t.Wt;
  }
  function Js(t, i) {
    return void 0 !== i.customValues && (t.Iw = i.customValues), t;
  }
  function Qs(t) {
    return (i, s, n, e3, r2, h2) => (function(t2, i2) {
      return i2 ? i2(t2) : Us(t2);
    })(n, h2) ? Js({ wt: i, Re: s, yw: e3 }, n) : Js(t(i, s, n, e3, r2), n);
  }
  function tn(t) {
    return { Candlestick: Qs(Xs), Bar: Qs(Ks), Area: Qs(Ys), Baseline: Qs(js), Histogram: Qs(qs), Line: Qs(qs), Custom: Qs(Zs) }[t];
  }
  function sn(t) {
    return { Re: 0, Ew: /* @__PURE__ */ new Map(), Hh: t };
  }
  function nn(t, i) {
    if (void 0 !== t && 0 !== t.length) return { Aw: i.key(t[0].wt), zw: i.key(t[t.length - 1].wt) };
  }
  function en(t) {
    let i;
    return t.forEach(((t2) => {
      void 0 === i && (i = t2.yw);
    })), _(i);
  }
  var rn = class {
    constructor(t) {
      this.Lw = /* @__PURE__ */ new Map(), this.Ow = /* @__PURE__ */ new Map(), this.Nw = /* @__PURE__ */ new Map(), this.Fw = [], this.o_ = t;
    }
    m() {
      this.Lw.clear(), this.Ow.clear(), this.Nw.clear(), this.Fw = [];
    }
    Ww(t, i) {
      let s = 0 !== this.Lw.size, n = false;
      const e3 = this.Ow.get(t);
      if (void 0 !== e3) if (1 === this.Ow.size) s = false, n = true, this.Lw.clear();
      else for (const i2 of this.Fw) i2.pointData.Ew.delete(t) && (n = true);
      let r2 = [];
      if (0 !== i.length) {
        const s2 = i.map(((t2) => t2.time)), e4 = this.o_.createConverterToInternalObj(i), h3 = tn(t.Rr()), a2 = t.ca(), l2 = t.fa();
        r2 = i.map(((i2, r3) => {
          const o2 = e4(i2.time), _2 = this.o_.key(o2);
          let u2 = this.Lw.get(_2);
          void 0 === u2 && (u2 = sn(o2), this.Lw.set(_2, u2), n = true);
          const c2 = h3(o2, u2.Re, i2, s2[r3], a2, l2);
          return u2.Ew.set(t, c2), c2;
        }));
      }
      s && this.Hw(), this.Uw(t, r2);
      let h2 = -1;
      if (n) {
        const t2 = [];
        this.Lw.forEach(((i2) => {
          t2.push({ timeWeight: 0, time: i2.Hh, pointData: i2, originalTime: en(i2.Ew) });
        })), t2.sort(((t3, i2) => this.o_.key(t3.time) - this.o_.key(i2.time))), h2 = this.$w(t2);
      }
      return this.qw(t, h2, (function(t2, i2, s2) {
        const n2 = nn(t2, s2), e4 = nn(i2, s2);
        if (void 0 !== n2 && void 0 !== e4) return { Yw: false, zh: n2.zw >= e4.zw && n2.Aw >= e4.Aw };
      })(this.Ow.get(t), e3, this.o_));
    }
    Ac(t) {
      return this.Ww(t, []);
    }
    jw(t, i, s) {
      const n = i;
      !(function(t2) {
        void 0 === t2.yw && (t2.yw = t2.time);
      })(n), this.o_.preprocessData(i);
      const e3 = this.o_.createConverterToInternalObj([i])(i.time), r2 = this.Nw.get(t);
      if (!s && void 0 !== r2 && this.o_.key(e3) < this.o_.key(r2)) throw new Error(`Cannot update oldest data, last time=${r2}, new time=${e3}`);
      let h2 = this.Lw.get(this.o_.key(e3));
      if (s && void 0 === h2) throw new Error("Cannot update non-existing data point when historicalUpdate is true");
      const a2 = void 0 === h2;
      void 0 === h2 && (h2 = sn(e3), this.Lw.set(this.o_.key(e3), h2));
      const l2 = tn(t.Rr()), o2 = t.ca(), _2 = t.fa(), u2 = l2(e3, h2.Re, i, n.yw, o2, _2);
      h2.Ew.set(t, u2), s ? this.Kw(t, u2, h2.Re) : this.Xw(t, u2);
      const c2 = { zh: Gs(u2), Yw: s };
      if (!a2) return this.qw(t, -1, c2);
      const d2 = { timeWeight: 0, time: h2.Hh, pointData: h2, originalTime: en(h2.Ew) }, f2 = yt(this.Fw, this.o_.key(d2.time), ((t2, i2) => this.o_.key(t2.time) < i2));
      this.Fw.splice(f2, 0, d2);
      for (let t2 = f2; t2 < this.Fw.length; ++t2) hn(this.Fw[t2].pointData, t2);
      return this.o_.fillWeightsForPoints(this.Fw, f2), this.qw(t, f2, c2);
    }
    Zw(t, i) {
      const s = this.Ow.get(t);
      if (void 0 === s || i <= 0) return [[], this.Gw()];
      i = Math.min(i, s.length);
      const n = s.splice(-i).reverse();
      0 === s.length ? this.Nw.delete(t) : this.Nw.set(t, s[s.length - 1].wt);
      for (const i2 of n) {
        const s2 = this.Lw.get(this.o_.key(i2.wt));
        if (s2 && (s2.Ew.delete(t), 0 === s2.Ew.size)) {
          this.Lw.delete(this.o_.key(s2.Hh)), this.Fw.splice(s2.Re, 1);
          for (let t2 = s2.Re; t2 < this.Fw.length; ++t2) hn(this.Fw[t2].pointData, t2);
        }
      }
      return [n, this.qw(t, this.Fw.length - 1, { Yw: false, zh: false })];
    }
    Xw(t, i) {
      let s = this.Ow.get(t);
      void 0 === s && (s = [], this.Ow.set(t, s));
      const n = 0 !== s.length ? s[s.length - 1] : null;
      null === n || this.o_.key(i.wt) > this.o_.key(n.wt) ? Gs(i) && s.push(i) : Gs(i) ? s[s.length - 1] = i : s.splice(-1, 1), this.Nw.set(t, i.wt);
    }
    Kw(t, i, s) {
      const n = this.Ow.get(t);
      if (void 0 === n) return;
      const e3 = yt(n, s, ((t2, i2) => t2.Re < i2));
      Gs(i) ? n[e3] = i : n.splice(e3, 1);
    }
    Uw(t, i) {
      0 !== i.length ? (this.Ow.set(t, i.filter(Gs)), this.Nw.set(t, i[i.length - 1].wt)) : (this.Ow.delete(t), this.Nw.delete(t));
    }
    Hw() {
      for (const t of this.Fw) 0 === t.pointData.Ew.size && this.Lw.delete(this.o_.key(t.time));
    }
    $w(t) {
      let i = -1;
      for (let s = 0; s < this.Fw.length && s < t.length; ++s) {
        const n = this.Fw[s], e3 = t[s];
        if (this.o_.key(n.time) !== this.o_.key(e3.time)) {
          i = s;
          break;
        }
        e3.timeWeight = n.timeWeight, hn(e3.pointData, s);
      }
      if (-1 === i && this.Fw.length !== t.length && (i = Math.min(this.Fw.length, t.length)), -1 === i) return -1;
      for (let s = i; s < t.length; ++s) hn(t[s].pointData, s);
      return this.o_.fillWeightsForPoints(t, i), this.Fw = t, i;
    }
    Jw() {
      if (0 === this.Ow.size) return null;
      let t = 0;
      return this.Ow.forEach(((i) => {
        0 !== i.length && (t = Math.max(t, i[i.length - 1].Re));
      })), t;
    }
    qw(t, i, s) {
      const n = this.Gw();
      if (-1 !== i) this.Ow.forEach(((i2, e3) => {
        n.Oo.set(e3, { se: i2, Qw: e3 === t ? s : void 0 });
      })), this.Ow.has(t) || n.Oo.set(t, { se: [], Qw: s }), n.Et.tg = this.Fw, n.Et.ig = i;
      else {
        const i2 = this.Ow.get(t);
        n.Oo.set(t, { se: i2 || [], Qw: s });
      }
      return n;
    }
    Gw() {
      return { Oo: /* @__PURE__ */ new Map(), Et: { _u: this.Jw() } };
    }
  };
  function hn(t, i) {
    t.Re = i, t.Ew.forEach(((t2) => {
      t2.Re = i;
    }));
  }
  function an(t, i) {
    return t.wt < i;
  }
  function ln(t, i) {
    return i < t.wt;
  }
  function on(t, i, s) {
    const n = i.Uh(), e3 = i.bi(), r2 = yt(t, n, an), h2 = kt(t, e3, ln);
    if (!s) return { from: r2, to: h2 };
    let a2 = r2, l2 = h2;
    return r2 > 0 && r2 < t.length && t[r2].wt >= n && (a2 = r2 - 1), h2 > 0 && h2 < t.length && t[h2 - 1].wt <= e3 && (l2 = h2 + 1), { from: a2, to: l2 };
  }
  var _n = class {
    constructor(t, i, s) {
      this.sg = true, this.ng = true, this.eg = true, this.rg = [], this.hg = null, this.Jn = t, this.Qn = i, this.ag = s;
    }
    yt(t) {
      this.sg = true, "data" === t && (this.ng = true), "options" === t && (this.eg = true);
    }
    Tt() {
      return this.Jn.Vt() ? (this.lg(), null === this.hg ? null : this.og) : null;
    }
    _g() {
      this.rg = this.rg.map(((t) => ({ ...t, ...this.Jn.Rh().Dr(t.wt) })));
    }
    ug() {
      this.hg = null;
    }
    lg() {
      this.ng && (this.cg(), this.ng = false), this.eg && (this._g(), this.eg = false), this.sg && (this.dg(), this.sg = false);
    }
    dg() {
      const t = this.Jn.Ft(), i = this.Qn.Et();
      if (this.ug(), i.Ki() || t.Ki()) return;
      const s = i.Pe();
      if (null === s) return;
      if (0 === this.Jn.Xs().zr()) return;
      const n = this.Jn.zt();
      null !== n && (this.hg = on(this.rg, s, this.ag), this.fg(t, i, n.Wt), this.pg());
    }
  };
  var un = class {
    constructor(t, i) {
      this.vg = t, this.Yi = i;
    }
    nt(t, i, s) {
      this.vg.draw(t, this.Yi, i, s);
    }
  };
  var cn = class extends _n {
    constructor(t, i, s) {
      super(t, i, false), this.sh = s, this.og = new un(this.sh.renderer(), ((i2) => {
        const s2 = t.zt();
        return null === s2 ? null : t.Ft().Nt(i2, s2.Wt);
      }));
    }
    da(t) {
      return this.sh.priceValueBuilder(t);
    }
    pa(t) {
      return this.sh.isWhitespace(t);
    }
    cg() {
      const t = this.Jn.Rh();
      this.rg = this.Jn.Xs().Hr().map(((i) => ({ wt: i.Re, _t: NaN, ...t.Dr(i.Re), mg: i.se })));
    }
    fg(t, i) {
      i.uu(this.rg, b(this.hg));
    }
    pg() {
      this.sh.update({ bars: this.rg.map(dn), barSpacing: this.Qn.Et().mu(), visibleRange: this.hg }, this.Jn.N());
    }
  };
  function dn(t) {
    return { x: t._t, time: t.wt, originalData: t.mg, barColor: t.cr };
  }
  var fn = { color: "#2196f3" };
  var pn = (t, i, s) => {
    const n = c(s);
    return new cn(t, i, n);
  };
  function vn(t) {
    const i = { value: t.Wt[3], time: t.yw };
    return void 0 !== t.Iw && (i.customValues = t.Iw), i;
  }
  function mn(t) {
    const i = vn(t);
    return void 0 !== t.R && (i.color = t.R), i;
  }
  function wn(t) {
    const i = vn(t);
    return void 0 !== t.vt && (i.lineColor = t.vt), void 0 !== t.mr && (i.topColor = t.mr), void 0 !== t.wr && (i.bottomColor = t.wr), i;
  }
  function gn(t) {
    const i = vn(t);
    return void 0 !== t.gr && (i.topLineColor = t.gr), void 0 !== t.Mr && (i.bottomLineColor = t.Mr), void 0 !== t.br && (i.topFillColor1 = t.br), void 0 !== t.Sr && (i.topFillColor2 = t.Sr), void 0 !== t.Cr && (i.bottomFillColor1 = t.Cr), void 0 !== t.Pr && (i.bottomFillColor2 = t.Pr), i;
  }
  function Mn(t) {
    const i = { open: t.Wt[0], high: t.Wt[1], low: t.Wt[2], close: t.Wt[3], time: t.yw };
    return void 0 !== t.Iw && (i.customValues = t.Iw), i;
  }
  function bn(t) {
    const i = Mn(t);
    return void 0 !== t.R && (i.color = t.R), i;
  }
  function Sn(t) {
    const i = Mn(t), { R: s, Ht: n, vr: e3 } = t;
    return void 0 !== s && (i.color = s), void 0 !== n && (i.borderColor = n), void 0 !== e3 && (i.wickColor = e3), i;
  }
  function xn(t) {
    return { Area: wn, Line: mn, Baseline: gn, Histogram: mn, Bar: bn, Candlestick: Sn, Custom: Cn }[t];
  }
  function Cn(t) {
    const i = t.yw;
    return { ...t.se, time: i };
  }
  var Pn = { vertLine: { color: "#9598A1", width: 1, style: 3, visible: true, labelVisible: true, labelBackgroundColor: "#131722" }, horzLine: { color: "#9598A1", width: 1, style: 3, visible: true, labelVisible: true, labelBackgroundColor: "#131722" }, mode: 1 };
  var yn = { vertLines: { color: "#D6DCDE", style: 0, visible: true }, horzLines: { color: "#D6DCDE", style: 0, visible: true } };
  var kn = { background: { type: "solid", color: "#FFFFFF" }, textColor: "#191919", fontSize: 12, fontFamily: S, panes: { enableResize: true, separatorColor: "#E0E3EB", separatorHoverColor: "rgba(178, 181, 189, 0.2)" }, attributionLogo: true, colorSpace: "srgb", colorParsers: [] };
  var Tn = { autoScale: true, mode: 0, invertScale: false, alignLabels: true, borderVisible: true, borderColor: "#2B2B43", entireTextOnly: false, visible: false, ticksVisible: false, scaleMargins: { bottom: 0.1, top: 0.2 }, minimumWidth: 0, ensureEdgeTickMarksVisible: false };
  var Rn = { rightOffset: 0, barSpacing: 6, minBarSpacing: 0.5, maxBarSpacing: 0, fixLeftEdge: false, fixRightEdge: false, lockVisibleTimeRangeOnResize: false, rightBarStaysOnScroll: false, borderVisible: true, borderColor: "#2B2B43", visible: true, timeVisible: false, secondsVisible: true, shiftVisibleRangeOnNewBar: true, allowShiftVisibleRangeOnWhitespaceReplacement: false, ticksVisible: false, uniformDistribution: false, minimumHeight: 0, allowBoldLabels: true, ignoreWhitespaceIndices: false };
  function Dn() {
    return { addDefaultPane: true, width: 0, height: 0, autoSize: false, layout: kn, crosshair: Pn, grid: yn, overlayPriceScales: { ...Tn }, leftPriceScale: { ...Tn, visible: false }, rightPriceScale: { ...Tn, visible: true }, timeScale: Rn, localization: { locale: rs ? navigator.language : "", dateFormat: "dd MMM 'yy" }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }, handleScale: { axisPressedMouseMove: { time: true, price: true }, axisDoubleClickReset: { time: true, price: true }, mouseWheel: true, pinch: true }, kineticScroll: { mouse: false, touch: true }, trackingMode: { exitMode: 1 } };
  }
  var Vn = class {
    constructor(t, i, s) {
      this.Hf = t, this.wg = i, this.gg = s ?? 0;
    }
    applyOptions(t) {
      this.Hf.Qt().oc(this.wg, t, this.gg);
    }
    options() {
      return this.Yi().N();
    }
    width() {
      return Z(this.wg) ? this.Hf.ow(this.wg) : 0;
    }
    setVisibleRange(t) {
      this.setAutoScale(false), this.Yi().Fl(new mt(t.from, t.to));
    }
    getVisibleRange() {
      let t, i, s = this.Yi().Qe();
      if (null === s) return null;
      if (this.Yi().Ja()) {
        const n = this.Yi().fo(), e3 = Fi(n);
        s = ci(s, this.Yi().tl()), t = Number((Math.round(s.$e() / n) * n).toFixed(e3)), i = Number((Math.round(s.qe() / n) * n).toFixed(e3));
      } else t = s.$e(), i = s.qe();
      return { from: t, to: i };
    }
    setAutoScale(t) {
      this.applyOptions({ autoScale: t });
    }
    Yi() {
      return u(this.Hf.Qt()._c(this.wg, this.gg)).Ft;
    }
  };
  var Bn = class {
    constructor(t, i, s, n) {
      this.Hf = t, this.Pt = s, this.Mg = i, this.bg = n;
    }
    getHeight() {
      return this.Pt.$t();
    }
    setHeight(t) {
      const i = this.Hf.Qt(), s = i.Uc(this.Pt);
      i.vc(s, t);
    }
    getStretchFactor() {
      return this.Pt.Bo();
    }
    setStretchFactor(t) {
      this.Pt.Io(t), this.Hf.Qt().Ih();
    }
    paneIndex() {
      return this.Hf.Qt().Uc(this.Pt);
    }
    moveTo(t) {
      const i = this.paneIndex();
      i !== t && (o(t >= 0 && t < this.Hf.$f().length, "Invalid pane index"), this.Hf.Qt().wc(i, t));
    }
    getSeries() {
      return this.Pt.Oo().map(((t) => this.Mg(t))) ?? [];
    }
    getHTMLElement() {
      const t = this.Hf.$f();
      return t && 0 !== t.length && t[this.paneIndex()] ? t[this.paneIndex()].Zf() : null;
    }
    attachPrimitive(t) {
      this.Pt._a(t), t.attached && t.attached({ chart: this.bg, requestUpdate: () => this.Pt.Qt().Ih() });
    }
    detachPrimitive(t) {
      this.Pt.ua(t);
    }
    priceScale(t) {
      if (null === this.Pt.Do(t)) throw new Error(`Cannot find price scale with id: ${t}`);
      return new Vn(this.Hf, t, this.paneIndex());
    }
    setPreserveEmptyPane(t) {
      this.Pt.zo(t);
    }
    preserveEmptyPane() {
      return this.Pt.Lo();
    }
    addCustomSeries(t, i = {}, s = 0) {
      return this.bg.addCustomSeries(t, i, s);
    }
    addSeries(t, i = {}) {
      return this.bg.addSeries(t, i, this.paneIndex());
    }
  };
  var In = { color: "#FF0000", price: 0, lineStyle: 2, lineWidth: 1, lineVisible: true, axisLabelVisible: true, title: "", axisLabelColor: "", axisLabelTextColor: "" };
  var En = class {
    constructor(t) {
      this.ir = t;
    }
    applyOptions(t) {
      this.ir.hr(t);
    }
    options() {
      return this.ir.N();
    }
    Sg() {
      return this.ir;
    }
  };
  var An = class {
    constructor(t, i, s, n, e3, r2) {
      this.xg = new d(), this.Jn = t, this.Cg = i, this.Pg = s, this.o_ = e3, this.bg = n, this.yg = r2;
    }
    m() {
      this.xg.m();
    }
    priceFormatter() {
      return this.Jn.ea();
    }
    priceToCoordinate(t) {
      const i = this.Jn.zt();
      return null === i ? null : this.Jn.Ft().Nt(t, i.Wt);
    }
    coordinateToPrice(t) {
      const i = this.Jn.zt();
      return null === i ? null : this.Jn.Ft().Ts(t, i.Wt);
    }
    barsInLogicalRange(t) {
      if (null === t) return null;
      const i = new Vi(new Ti(t.from, t.to)).y_(), s = this.Jn.Xs();
      if (s.Ki()) return null;
      const n = s.Fr(i.Uh(), 1), e3 = s.Fr(i.bi(), -1), r2 = u(s.Lr()), h2 = u(s.Ks());
      if (null !== n && null !== e3 && n.Re > e3.Re) return { barsBefore: t.from - r2, barsAfter: h2 - t.to };
      const a2 = { barsBefore: null === n || n.Re === r2 ? t.from - r2 : n.Re - r2, barsAfter: null === e3 || e3.Re === h2 ? h2 - t.to : h2 - e3.Re };
      return null !== n && null !== e3 && (a2.from = n.yw, a2.to = e3.yw), a2;
    }
    setData(t) {
      this.o_, this.Jn.Rr(), this.Cg.kg(this.Jn, t), this.Tg("full");
    }
    update(t, i = false) {
      this.Jn.Rr(), this.Cg.Rg(this.Jn, t, i), this.Tg("update");
    }
    pop(t = 1) {
      const i = this.Cg.Dg(this.Jn, t);
      0 !== i.length && this.Tg("update");
      const s = xn(this.seriesType());
      return i.map(((t2) => s(t2)));
    }
    dataByIndex(t, i) {
      const s = this.Jn.Xs().Fr(t, i);
      if (null === s) return null;
      return xn(this.seriesType())(s);
    }
    data() {
      const t = xn(this.seriesType());
      return this.Jn.Xs().Hr().map(((i) => t(i)));
    }
    subscribeDataChanged(t) {
      this.xg.i(t);
    }
    unsubscribeDataChanged(t) {
      this.xg._(t);
    }
    applyOptions(t) {
      this.Jn.hr(t);
    }
    options() {
      return g(this.Jn.N());
    }
    priceScale() {
      return this.Pg.priceScale(this.Jn.Ft().ma(), this.getPane().paneIndex());
    }
    createPriceLine(t) {
      const i = f(g(In), t), s = this.Jn.Oh(i);
      return new En(s);
    }
    removePriceLine(t) {
      this.Jn.Nh(t.Sg());
    }
    priceLines() {
      return this.Jn.Fh().map(((t) => new En(t)));
    }
    seriesType() {
      return this.Jn.Rr();
    }
    lastValueData(t) {
      const i = this.Jn.ye(t);
      return i.ke ? { noData: true } : { noData: false, price: i.gt, color: i.R };
    }
    attachPrimitive(t) {
      this.Jn._a(t), t.attached && t.attached({ chart: this.bg, series: this, requestUpdate: () => this.Jn.Qt().Ih(), horzScaleBehavior: this.o_ });
    }
    detachPrimitive(t) {
      this.Jn.ua(t), t.detached && t.detached(), this.Jn.Qt().Ih();
    }
    getPane() {
      const t = this.Jn, i = u(this.Jn.Qt().Hn(t));
      return this.yg(i);
    }
    moveToPane(t) {
      this.Jn.Qt().Nc(this.Jn, t);
    }
    seriesOrder() {
      const t = this.Jn.Qt().Hn(this.Jn);
      return null === t ? -1 : t.Oo().indexOf(this.Jn);
    }
    setSeriesOrder(t) {
      const i = this.Jn.Qt().Hn(this.Jn);
      null !== i && i.Qo(this.Jn, t);
    }
    Tg(t) {
      this.xg.v() && this.xg.p(t);
    }
  };
  var zn = class {
    constructor(t, i, s) {
      this.Vg = new d(), this.z_ = new d(), this.gm = new d(), this.ts = t, this.uh = t.Et(), this.Zm = i, this.uh.Vu().i(this.Bg.bind(this)), this.uh.Bu().i(this.Ig.bind(this)), this.Zm.ym().i(this.Eg.bind(this)), this.o_ = s;
    }
    m() {
      this.uh.Vu().u(this), this.uh.Bu().u(this), this.Zm.ym().u(this), this.Vg.m(), this.z_.m(), this.gm.m();
    }
    scrollPosition() {
      return this.uh.gu();
    }
    scrollToPosition(t, i) {
      i ? this.uh.Tu(t, 1e3) : this.ts.fn(t);
    }
    scrollToRealTime() {
      this.uh.ku();
    }
    getVisibleRange() {
      const t = this.uh.nu();
      return null === t ? null : { from: t.from.originalTime, to: t.to.originalTime };
    }
    setVisibleRange(t) {
      const i = { from: this.o_.convertHorzItemToInternal(t.from), to: this.o_.convertHorzItemToInternal(t.to) }, s = this.uh.au(i);
      this.ts.Lc(s);
    }
    getVisibleLogicalRange() {
      const t = this.uh.su();
      return null === t ? null : { from: t.Uh(), to: t.bi() };
    }
    setVisibleLogicalRange(t) {
      o(t.from <= t.to, "The from index cannot be after the to index."), this.ts.Lc(t);
    }
    resetTimeScale() {
      this.ts.cn();
    }
    fitContent() {
      this.ts.Au();
    }
    logicalToCoordinate(t) {
      const i = this.ts.Et();
      return i.Ki() ? null : i.qt(t);
    }
    coordinateToLogical(t) {
      return this.uh.Ki() ? null : this.uh.cu(t);
    }
    timeToIndex(t, i) {
      const s = this.o_.convertHorzItemToInternal(t);
      return this.uh.Q_(s, i);
    }
    timeToCoordinate(t) {
      const i = this.timeToIndex(t, false);
      return null === i ? null : this.uh.qt(i);
    }
    coordinateToTime(t) {
      const i = this.ts.Et(), s = i.cu(t), n = i.ss(s);
      return null === n ? null : n.originalTime;
    }
    width() {
      return this.Zm.Gf().width;
    }
    height() {
      return this.Zm.Gf().height;
    }
    subscribeVisibleTimeRangeChange(t) {
      this.Vg.i(t);
    }
    unsubscribeVisibleTimeRangeChange(t) {
      this.Vg._(t);
    }
    subscribeVisibleLogicalRangeChange(t) {
      this.z_.i(t);
    }
    unsubscribeVisibleLogicalRangeChange(t) {
      this.z_._(t);
    }
    subscribeSizeChange(t) {
      this.gm.i(t);
    }
    unsubscribeSizeChange(t) {
      this.gm._(t);
    }
    applyOptions(t) {
      this.uh.hr(t);
    }
    options() {
      return { ...g(this.uh.N()), barSpacing: this.uh.mu() };
    }
    Bg() {
      this.Vg.v() && this.Vg.p(this.getVisibleRange());
    }
    Ig() {
      this.z_.v() && this.z_.p(this.getVisibleLogicalRange());
    }
    Eg(t) {
      this.gm.p(t.width, t.height);
    }
  };
  function Ln(t) {
    return (function(t2) {
      if (w(t2.handleScale)) {
        const i2 = t2.handleScale;
        t2.handleScale = { axisDoubleClickReset: { time: i2, price: i2 }, axisPressedMouseMove: { time: i2, price: i2 }, mouseWheel: i2, pinch: i2 };
      } else if (void 0 !== t2.handleScale) {
        const { axisPressedMouseMove: i2, axisDoubleClickReset: s } = t2.handleScale;
        w(i2) && (t2.handleScale.axisPressedMouseMove = { time: i2, price: i2 }), w(s) && (t2.handleScale.axisDoubleClickReset = { time: s, price: s });
      }
      const i = t2.handleScroll;
      w(i) && (t2.handleScroll = { horzTouchDrag: i, vertTouchDrag: i, mouseWheel: i, pressedMouseMove: i });
    })(t), t;
  }
  var On = class {
    constructor(t, i, s) {
      this.Ag = /* @__PURE__ */ new Map(), this.zg = /* @__PURE__ */ new Map(), this.Lg = new d(), this.Og = new d(), this.Ng = new d(), this.qu = /* @__PURE__ */ new WeakMap(), this.Fg = new rn(i);
      const n = void 0 === s ? g(Dn()) : f(g(Dn()), Ln(s));
      this.Wg = i, this.Hf = new Ws(t, n, i), this.Hf.Xv().i(((t2) => {
        this.Lg.v() && this.Lg.p(this.Hg(t2()));
      }), this), this.Hf.Zv().i(((t2) => {
        this.Og.v() && this.Og.p(this.Hg(t2()));
      }), this), this.Hf.cc().i(((t2) => {
        this.Ng.v() && this.Ng.p(this.Hg(t2()));
      }), this);
      const e3 = this.Hf.Qt();
      this.Ug = new zn(e3, this.Hf.iw(), this.Wg);
    }
    remove() {
      this.Hf.Xv().u(this), this.Hf.Zv().u(this), this.Hf.cc().u(this), this.Ug.m(), this.Hf.m(), this.Ag.clear(), this.zg.clear(), this.Lg.m(), this.Og.m(), this.Ng.m(), this.Fg.m();
    }
    resize(t, i, s) {
      this.autoSizeActive() || this.Hf.Jm(t, i, s);
    }
    addCustomSeries(t, i = {}, s = 0) {
      const n = ((t2) => ({ type: "Custom", isBuiltIn: false, defaultOptions: { ...fn, ...t2.defaultOptions() }, $g: pn, qg: t2 }))(c(t));
      return this.Yg(n, i, s);
    }
    addSeries(t, i = {}, s = 0) {
      return this.Yg(t, i, s);
    }
    removeSeries(t) {
      const i = _(this.Ag.get(t)), s = this.Fg.Ac(i);
      this.Hf.Qt().Ac(i), this.jg(s), this.Ag.delete(t), this.zg.delete(i);
    }
    kg(t, i) {
      this.jg(this.Fg.Ww(t, i));
    }
    Rg(t, i, s) {
      this.jg(this.Fg.jw(t, i, s));
    }
    Dg(t, i) {
      const [s, n] = this.Fg.Zw(t, i);
      return 0 !== s.length && this.jg(n), s;
    }
    subscribeClick(t) {
      this.Lg.i(t);
    }
    unsubscribeClick(t) {
      this.Lg._(t);
    }
    subscribeCrosshairMove(t) {
      this.Ng.i(t);
    }
    unsubscribeCrosshairMove(t) {
      this.Ng._(t);
    }
    subscribeDblClick(t) {
      this.Og.i(t);
    }
    unsubscribeDblClick(t) {
      this.Og._(t);
    }
    priceScale(t, i = 0) {
      return new Vn(this.Hf, t, i);
    }
    timeScale() {
      return this.Ug;
    }
    applyOptions(t) {
      this.Hf.hr(Ln(t));
    }
    options() {
      return this.Hf.N();
    }
    takeScreenshot(t = false, i = false) {
      let s, n;
      try {
        i || (s = this.Hf.Qt().N().crosshair.mode, this.Hf.hr({ crosshair: { mode: 2 } })), n = this.Hf.aw(t);
      } finally {
        i || void 0 === s || this.Hf.Qt().hr({ crosshair: { mode: s } });
      }
      return n;
    }
    addPane(t = false) {
      const i = this.Hf.Qt().$c();
      return i.zo(t), this.Kg(i);
    }
    removePane(t) {
      this.Hf.Qt().fc(t);
    }
    swapPanes(t, i) {
      this.Hf.Qt().mc(t, i);
    }
    autoSizeActive() {
      return this.Hf.cw();
    }
    chartElement() {
      return this.Hf.ip();
    }
    panes() {
      return this.Hf.Qt().$s().map(((t) => this.Kg(t)));
    }
    paneSize(t = 0) {
      const i = this.Hf.pw(t);
      return { height: i.height, width: i.width };
    }
    setCrosshairPosition(t, i, s) {
      const n = this.Ag.get(s);
      if (void 0 === n) return;
      const e3 = this.Hf.Qt().Hn(n);
      null !== e3 && this.Hf.Qt().Rc(t, i, e3);
    }
    clearCrosshairPosition() {
      this.Hf.Qt().Dc(true);
    }
    horzBehaviour() {
      return this.Wg;
    }
    Yg(t, i = {}, s = 0) {
      o(void 0 !== t.$g), (function(t2) {
        if (void 0 === t2 || "custom" === t2.type) return;
        const i2 = t2;
        void 0 !== i2.minMove && void 0 === i2.precision && (i2.precision = Fi(i2.minMove));
      })(i.priceFormat), "Candlestick" === t.type && (function(t2) {
        void 0 !== t2.borderColor && (t2.borderUpColor = t2.borderColor, t2.borderDownColor = t2.borderColor), void 0 !== t2.wickColor && (t2.wickUpColor = t2.wickColor, t2.wickDownColor = t2.wickColor);
      })(i);
      const n = f(g(e), g(t.defaultOptions), i), r2 = t.$g, h2 = new Kt(this.Hf.Qt(), t.type, n, r2, t.qg);
      this.Hf.Qt().Ic(h2, s);
      const a2 = new An(h2, this, this, this, this.Wg, ((t2) => this.Kg(t2)));
      return this.Ag.set(a2, h2), this.zg.set(h2, a2), a2;
    }
    jg(t) {
      const i = this.Hf.Qt();
      i.Vc(t.Et._u, t.Et.tg, t.Et.ig), t.Oo.forEach(((t2, i2) => i2.ht(t2.se, t2.Qw))), i.Et().K_(), i.vu();
    }
    Xg(t) {
      return _(this.zg.get(t));
    }
    Hg(t) {
      const i = /* @__PURE__ */ new Map();
      t.Dw.forEach(((t2, s2) => {
        const n = s2.Rr(), e3 = xn(n)(t2);
        if ("Custom" !== n) o($s(e3));
        else {
          const t3 = s2.fa();
          o(!t3 || false === t3(e3));
        }
        i.set(this.Xg(s2), e3);
      }));
      const s = void 0 !== t.Rw && this.zg.has(t.Rw) ? this.Xg(t.Rw) : void 0;
      return { time: t.yw, logical: t.Re, point: t.kw, paneIndex: t.Tw, hoveredSeries: s, hoveredObjectId: t.Vw, seriesData: i, sourceEvent: t.Bw };
    }
    Kg(t) {
      let i = this.qu.get(t);
      return i || (i = new Bn(this.Hf, ((t2) => this.Xg(t2)), t, this), this.qu.set(t, i)), i;
    }
  };
  function Nn(t) {
    if (m(t)) {
      const i = document.getElementById(t);
      return o(null !== i, `Cannot find element in DOM with id=${t}`), i;
    }
    return t;
  }
  function Fn(t, i, s) {
    const n = Nn(t), e3 = new On(n, i, s);
    return i.setOptions(e3.options()), e3;
  }
  function Wn(t, i) {
    return Fn(t, new es(), es.ld(i));
  }
  var Me = class extends _n {
    constructor(t, i) {
      super(t, i, false);
    }
    fg(t, i, s) {
      i.uu(this.rg, b(this.hg)), t.ql(this.rg, s, b(this.hg));
    }
    VM(t, i, s) {
      return { wt: t, qh: i.Wt[0], Yh: i.Wt[1], jh: i.Wt[2], Kh: i.Wt[3], _t: NaN, Yl: NaN, jl: NaN, Kl: NaN, Xl: NaN };
    }
    cg() {
      const t = this.Jn.Rh();
      this.rg = this.Jn.Xs().Hr().map(((i) => this.Gg(i.Re, i, t)));
    }
  };
  var xe = class extends R {
    constructor() {
      super(...arguments), this.Yt = null, this.yM = 0;
    }
    ht(t) {
      this.Yt = t;
    }
    et(t) {
      if (null === this.Yt || 0 === this.Yt.Xs.length || null === this.Yt.lt) return;
      const { horizontalPixelRatio: i } = t;
      if (this.yM = (function(t2, i2) {
        if (t2 >= 2.5 && t2 <= 4) return Math.floor(3 * i2);
        const s2 = 1 - 0.2 * Math.atan(Math.max(4, t2) - 4) / (0.5 * Math.PI), n2 = Math.floor(t2 * s2 * i2), e3 = Math.floor(t2 * i2), r2 = Math.min(n2, e3);
        return Math.max(Math.floor(i2), r2);
      })(this.Yt.mu, i), this.yM >= 2) {
        Math.floor(i) % 2 != this.yM % 2 && this.yM--;
      }
      const s = this.Yt.Xs;
      this.Yt.BM && this.IM(t, s, this.Yt.lt), this.Yt.Mi && this.uv(t, s, this.Yt.lt);
      const n = this.EM(i);
      (!this.Yt.Mi || this.yM > 2 * n) && this.AM(t, s, this.Yt.lt);
    }
    IM(t, i, s) {
      if (null === this.Yt) return;
      const { context: n, horizontalPixelRatio: e3, verticalPixelRatio: r2 } = t;
      let h2 = "", a2 = Math.min(Math.floor(e3), Math.floor(this.Yt.mu * e3));
      a2 = Math.max(Math.floor(e3), Math.min(a2, this.yM));
      const l2 = Math.floor(0.5 * a2);
      let o2 = null;
      for (let t2 = s.from; t2 < s.to; t2++) {
        const s2 = i[t2];
        s2.pr !== h2 && (n.fillStyle = s2.pr, h2 = s2.pr);
        const _2 = Math.round(Math.min(s2.Yl, s2.Xl) * r2), u2 = Math.round(Math.max(s2.Yl, s2.Xl) * r2), c2 = Math.round(s2.jl * r2), d2 = Math.round(s2.Kl * r2);
        let f2 = Math.round(e3 * s2._t) - l2;
        const p2 = f2 + a2 - 1;
        null !== o2 && (f2 = Math.max(o2 + 1, f2), f2 = Math.min(f2, p2));
        const v2 = p2 - f2 + 1;
        n.fillRect(f2, c2, v2, _2 - c2), n.fillRect(f2, u2 + 1, v2, d2 - u2), o2 = p2;
      }
    }
    EM(t) {
      let i = Math.floor(1 * t);
      this.yM <= 2 * i && (i = Math.floor(0.5 * (this.yM - 1)));
      const s = Math.max(Math.floor(t), i);
      return this.yM <= 2 * s ? Math.max(Math.floor(t), Math.floor(1 * t)) : s;
    }
    uv(t, i, s) {
      if (null === this.Yt) return;
      const { context: n, horizontalPixelRatio: e3, verticalPixelRatio: r2 } = t;
      let h2 = "";
      const a2 = this.EM(e3);
      let l2 = null;
      for (let t2 = s.from; t2 < s.to; t2++) {
        const s2 = i[t2];
        s2.dr !== h2 && (n.fillStyle = s2.dr, h2 = s2.dr);
        let o2 = Math.round(s2._t * e3) - Math.floor(0.5 * this.yM);
        const _2 = o2 + this.yM - 1, u2 = Math.round(Math.min(s2.Yl, s2.Xl) * r2), c2 = Math.round(Math.max(s2.Yl, s2.Xl) * r2);
        if (null !== l2 && (o2 = Math.max(l2 + 1, o2), o2 = Math.min(o2, _2)), this.Yt.mu * e3 > 2 * a2) z(n, o2, u2, _2 - o2 + 1, c2 - u2 + 1, a2);
        else {
          const t3 = _2 - o2 + 1;
          n.fillRect(o2, u2, t3, c2 - u2 + 1);
        }
        l2 = _2;
      }
    }
    AM(t, i, s) {
      if (null === this.Yt) return;
      const { context: n, horizontalPixelRatio: e3, verticalPixelRatio: r2 } = t;
      let h2 = "";
      const a2 = this.EM(e3);
      for (let t2 = s.from; t2 < s.to; t2++) {
        const s2 = i[t2];
        let l2 = Math.round(Math.min(s2.Yl, s2.Xl) * r2), o2 = Math.round(Math.max(s2.Yl, s2.Xl) * r2), _2 = Math.round(s2._t * e3) - Math.floor(0.5 * this.yM), u2 = _2 + this.yM - 1;
        if (s2.cr !== h2) {
          const t3 = s2.cr;
          n.fillStyle = t3, h2 = t3;
        }
        this.Yt.Mi && (_2 += a2, l2 += a2, u2 -= a2, o2 -= a2), l2 > o2 || n.fillRect(_2, l2, u2 - _2 + 1, o2 - l2 + 1);
      }
    }
  };
  var Ce = class extends Me {
    constructor() {
      super(...arguments), this.og = new xe();
    }
    Gg(t, i, s) {
      return { ...this.VM(t, i, s), ...s.Dr(t) };
    }
    pg() {
      const t = this.Jn.N();
      this.og.ht({ Xs: this.rg, mu: this.Qn.Et().mu(), BM: t.wickVisible, Mi: t.borderVisible, lt: this.hg });
    }
  };
  var Pe = { type: "Candlestick", isBuiltIn: true, defaultOptions: { upColor: "#26a69a", downColor: "#ef5350", wickVisible: true, borderVisible: true, borderColor: "#378658", borderUpColor: "#26a69a", borderDownColor: "#ef5350", wickColor: "#737375", wickUpColor: "#26a69a", wickDownColor: "#ef5350" }, $g: (t, i) => new Ce(t, i) };
  var je = class {
    constructor(t, i) {
      this.Jn = t, this.ah = i, this.WM();
    }
    detach() {
      this.Jn.detachPrimitive(this.ah);
    }
    getSeries() {
      return this.Jn;
    }
    applyOptions(t) {
      this.ah && this.ah.hr && this.ah.hr(t);
    }
    WM() {
      this.Jn.attachPrimitive(this.ah);
    }
  };
  var Ke = { autoScale: true, zOrder: "normal" };
  function Xe(t, i) {
    return ti(Math.min(Math.max(t, 12), 30) * i);
  }
  function Ze(t, i) {
    switch (t) {
      case "arrowDown":
      case "arrowUp":
        return Xe(i, 1);
      case "circle":
        return Xe(i, 0.8);
      case "square":
        return Xe(i, 0.7);
    }
  }
  function Ge(t) {
    return (function(t2) {
      const i = Math.ceil(t2);
      return i % 2 != 0 ? i - 1 : i;
    })(Xe(t, 1));
  }
  function Je(t) {
    return Math.max(Xe(t, 0.1), 3);
  }
  function Qe(t, i, s) {
    return i ? t : s ? Math.ceil(t / 2) : 0;
  }
  function tr(t, i, s, n) {
    const e3 = (Ze("arrowUp", n) - 1) / 2 * s._b, r2 = (ti(n / 2) - 1) / 2 * s._b;
    i.beginPath(), t ? (i.moveTo(s._t - e3, s.ut), i.lineTo(s._t, s.ut - e3), i.lineTo(s._t + e3, s.ut), i.lineTo(s._t + r2, s.ut), i.lineTo(s._t + r2, s.ut + e3), i.lineTo(s._t - r2, s.ut + e3), i.lineTo(s._t - r2, s.ut)) : (i.moveTo(s._t - e3, s.ut), i.lineTo(s._t, s.ut + e3), i.lineTo(s._t + e3, s.ut), i.lineTo(s._t + r2, s.ut), i.lineTo(s._t + r2, s.ut - e3), i.lineTo(s._t - r2, s.ut - e3), i.lineTo(s._t - r2, s.ut)), i.fill();
  }
  function ir(t, i, s, n, e3, r2) {
    const h2 = (Ze("arrowUp", n) - 1) / 2, a2 = (ti(n / 2) - 1) / 2;
    if (e3 >= i - a2 - 2 && e3 <= i + a2 + 2 && r2 >= (t ? s : s - h2) - 2 && r2 <= (t ? s + h2 : s) + 2) return true;
    return (() => {
      if (e3 < i - h2 - 3 || e3 > i + h2 + 3 || r2 < (t ? s - h2 - 3 : s) || r2 > (t ? s : s + h2 + 3)) return false;
      const n2 = Math.abs(e3 - i);
      return Math.abs(r2 - s) + 3 >= n2 / 2;
    })();
  }
  var sr = class {
    constructor() {
      this.Yt = null, this.On = new rt(), this.F = -1, this.W = "", this.Wp = "", this.ub = "normal";
    }
    ht(t) {
      this.Yt = t;
    }
    Nn(t, i, s) {
      this.F === t && this.W === i || (this.F = t, this.W = i, this.Wp = x(t, i), this.On.Bn()), this.ub = s;
    }
    jn(t, i) {
      if (null === this.Yt || null === this.Yt.lt) return null;
      for (let s = this.Yt.lt.from; s < this.Yt.lt.to; s++) {
        const n = this.Yt.ot[s];
        if (n && er(n, t, i)) return { zOrder: "normal", externalId: n.Kn ?? "" };
      }
      return null;
    }
    draw(t) {
      "aboveSeries" !== this.ub && t.useBitmapCoordinateSpace(((t2) => {
        this.et(t2);
      }));
    }
    drawBackground(t) {
      "aboveSeries" === this.ub && t.useBitmapCoordinateSpace(((t2) => {
        this.et(t2);
      }));
    }
    et({ context: t, horizontalPixelRatio: i, verticalPixelRatio: s }) {
      if (null !== this.Yt && null !== this.Yt.lt) {
        t.textBaseline = "middle", t.font = this.Wp;
        for (let n = this.Yt.lt.from; n < this.Yt.lt.to; n++) {
          const e3 = this.Yt.ot[n];
          void 0 !== e3.ri && (e3.ri.Qi = this.On.Vi(t, e3.ri.cb), e3.ri.$t = this.F, e3.ri._t = e3._t - e3.ri.Qi / 2), nr(e3, t, i, s);
        }
      }
    }
  };
  function nr(t, i, s, n) {
    i.fillStyle = t.R, void 0 !== t.ri && (function(t2, i2, s2, n2, e3, r2) {
      t2.save(), t2.scale(e3, r2), t2.fillText(i2, s2, n2), t2.restore();
    })(i, t.ri.cb, t.ri._t, t.ri.ut, s, n), (function(t2, i2, s2) {
      if (0 === t2.zr) return;
      switch (t2.fb) {
        case "arrowDown":
          return void tr(false, i2, s2, t2.zr);
        case "arrowUp":
          return void tr(true, i2, s2, t2.zr);
        case "circle":
          return void (function(t3, i3, s3) {
            const n2 = (Ze("circle", s3) - 1) / 2;
            t3.beginPath(), t3.arc(i3._t, i3.ut, n2 * i3._b, 0, 2 * Math.PI, false), t3.fill();
          })(i2, s2, t2.zr);
        case "square":
          return void (function(t3, i3, s3) {
            const n2 = Ze("square", s3), e3 = (n2 - 1) * i3._b / 2, r2 = i3._t - e3, h2 = i3.ut - e3;
            t3.fillRect(r2, h2, n2 * i3._b, n2 * i3._b);
          })(i2, s2, t2.zr);
      }
      t2.fb;
    })(t, i, (function(t2, i2, s2) {
      const n2 = Math.max(1, Math.floor(i2)) % 2 / 2;
      return { _t: Math.round(t2._t * i2) + n2, ut: t2.ut * s2, _b: i2 };
    })(t, s, n));
  }
  function er(t, i, s) {
    return !(void 0 === t.ri || !(function(t2, i2, s2, n, e3, r2) {
      const h2 = n / 2;
      return e3 >= t2 && e3 <= t2 + s2 && r2 >= i2 - h2 && r2 <= i2 + h2;
    })(t.ri._t, t.ri.ut, t.ri.Qi, t.ri.$t, i, s)) || (function(t2, i2, s2) {
      if (0 === t2.zr) return false;
      switch (t2.fb) {
        case "arrowDown":
          return ir(true, t2._t, t2.ut, t2.zr, i2, s2);
        case "arrowUp":
          return ir(false, t2._t, t2.ut, t2.zr, i2, s2);
        case "circle":
          return (function(t3, i3, s3, n, e3) {
            const r2 = 2 + Ze("circle", s3) / 2, h2 = t3 - n, a2 = i3 - e3;
            return Math.sqrt(h2 * h2 + a2 * a2) <= r2;
          })(t2._t, t2.ut, t2.zr, i2, s2);
        case "square":
          return (function(t3, i3, s3, n, e3) {
            const r2 = Ze("square", s3), h2 = (r2 - 1) / 2, a2 = t3 - h2, l2 = i3 - h2;
            return n >= a2 && n <= a2 + r2 && e3 >= l2 && e3 <= l2 + r2;
          })(t2._t, t2.ut, t2.zr, i2, s2);
      }
    })(t, i, s);
  }
  function rr(t) {
    return "atPriceTop" === t || "atPriceBottom" === t || "atPriceMiddle" === t;
  }
  function hr(t, i, s, n, e3, r2, h2, a2) {
    const l2 = (function(t2, i2, s2) {
      if (rr(i2.position) && void 0 !== i2.price) return i2.price;
      if ("value" in (n2 = t2) && "number" == typeof n2.value) return t2.value;
      var n2;
      if ((function(t3) {
        return "open" in t3 && "high" in t3 && "low" in t3 && "close" in t3;
      })(t2)) {
        if ("inBar" === i2.position) return t2.close;
        if ("aboveBar" === i2.position) return s2 ? t2.low : t2.high;
        if ("belowBar" === i2.position) return s2 ? t2.high : t2.low;
      }
    })(s, i, h2.priceScale().options().invertScale);
    if (void 0 === l2) return;
    const o2 = rr(i.position), _2 = a2.timeScale(), c2 = p(i.size) ? Math.max(i.size, 0) : 1, d2 = Ge(_2.options().barSpacing) * c2, f2 = d2 / 2;
    t.zr = d2;
    switch (i.position) {
      case "inBar":
      case "atPriceMiddle":
        return t.ut = u(h2.priceToCoordinate(l2)), void (void 0 !== t.ri && (t.ri.ut = t.ut + f2 + r2 + 0.6 * e3));
      case "aboveBar":
      case "atPriceTop": {
        const i2 = o2 ? 0 : n.pb;
        return t.ut = u(h2.priceToCoordinate(l2)) - f2 - i2, void 0 !== t.ri && (t.ri.ut = t.ut - f2 - 0.6 * e3, n.pb += 1.2 * e3), void (o2 || (n.pb += d2 + r2));
      }
      case "belowBar":
      case "atPriceBottom": {
        const i2 = o2 ? 0 : n.mb;
        return t.ut = u(h2.priceToCoordinate(l2)) + f2 + i2, void 0 !== t.ri && (t.ri.ut = t.ut + f2 + r2 + 0.6 * e3, n.mb += 1.2 * e3), void (o2 || (n.mb += d2 + r2));
      }
    }
  }
  var ar = class {
    constructor(t, i, s) {
      this.wb = [], this.xt = true, this.gb = true, this.Gt = new sr(), this.ge = t, this.Vp = i, this.Yt = { ot: [], lt: null }, this.Ps = s;
    }
    renderer() {
      if (!this.ge.options().visible) return null;
      this.xt && this.Mb();
      const t = this.Vp.options().layout;
      return this.Gt.Nn(t.fontSize, t.fontFamily, this.Ps.zOrder), this.Gt.ht(this.Yt), this.Gt;
    }
    bb(t) {
      this.wb = t, this.yt("data");
    }
    yt(t) {
      this.xt = true, "data" === t && (this.gb = true);
    }
    Sb(t) {
      this.xt = true, this.Ps = t;
    }
    zOrder() {
      return "aboveSeries" === this.Ps.zOrder ? "top" : this.Ps.zOrder;
    }
    Mb() {
      const t = this.Vp.timeScale(), i = this.wb;
      this.gb && (this.Yt.ot = i.map(((t2) => ({ wt: t2.time, _t: 0, ut: 0, zr: 0, fb: t2.shape, R: t2.color, Kn: t2.id, xb: t2.xb, ri: void 0 }))), this.gb = false);
      const s = this.Vp.options().layout;
      this.Yt.lt = null;
      const n = t.getVisibleLogicalRange();
      if (null === n) return;
      const e3 = new Ti(Math.floor(n.from), Math.ceil(n.to));
      if (null === this.ge.data()[0]) return;
      if (0 === this.Yt.ot.length) return;
      let r2 = NaN;
      const h2 = Je(t.options().barSpacing), a2 = { pb: h2, mb: h2 };
      this.Yt.lt = on(this.Yt.ot, e3, true);
      for (let n2 = this.Yt.lt.from; n2 < this.Yt.lt.to; n2++) {
        const e4 = i[n2];
        e4.time !== r2 && (a2.pb = h2, a2.mb = h2, r2 = e4.time);
        const l2 = this.Yt.ot[n2];
        l2._t = u(t.logicalToCoordinate(e4.time)), void 0 !== e4.text && e4.text.length > 0 && (l2.ri = { cb: e4.text, _t: 0, ut: 0, Qi: 0, $t: 0 });
        const o2 = this.ge.dataByIndex(e4.time, 0);
        null !== o2 && hr(l2, e4, o2, a2, s.fontSize, h2, this.ge, this.Vp);
      }
      this.xt = false;
    }
  };
  function lr(t) {
    return { ...Ke, ...t };
  }
  var or = class {
    constructor(t) {
      this.sh = null, this.wb = [], this.Cb = [], this.Pb = null, this.ge = null, this.Vp = null, this.yb = true, this.kb = null, this.Tb = null, this.Rb = null, this.Db = true, this.Ps = lr(t);
    }
    attached(t) {
      this.Vb(), this.Vp = t.chart, this.ge = t.series, this.sh = new ar(this.ge, u(this.Vp), this.Ps), this.lb = t.requestUpdate, this.ge.subscribeDataChanged(((t2) => this.Tg(t2))), this.Db = true, this.jM();
    }
    jM() {
      this.lb && this.lb();
    }
    detached() {
      this.ge && this.Pb && this.ge.unsubscribeDataChanged(this.Pb), this.Vp = null, this.ge = null, this.sh = null, this.Pb = null;
    }
    bb(t) {
      this.Db = true, this.wb = t, this.Vb(), this.yb = true, this.Tb = null, this.jM();
    }
    Bb() {
      return this.wb;
    }
    paneViews() {
      return this.sh ? [this.sh] : [];
    }
    updateAllViews() {
      this.Ib();
    }
    hitTest(t, i) {
      return this.sh ? this.sh.renderer()?.jn(t, i) ?? null : null;
    }
    autoscaleInfo(t, i) {
      if (this.Ps.autoScale && this.sh) {
        const t2 = this.Eb();
        if (t2) return { priceRange: null, margins: t2 };
      }
      return null;
    }
    hr(t) {
      this.Ps = lr({ ...this.Ps, ...t }), this.jM && this.jM();
    }
    Eb() {
      const t = u(this.Vp).timeScale().options().barSpacing;
      if (this.yb || t !== this.Rb) {
        if (this.Rb = t, this.wb.length > 0) {
          const i = Je(t), s = 1.5 * Ge(t) + 2 * i, n = this.Ab();
          this.kb = { above: Qe(s, n.aboveBar, n.inBar), below: Qe(s, n.belowBar, n.inBar) };
        } else this.kb = null;
        this.yb = false;
      }
      return this.kb;
    }
    Ab() {
      return null === this.Tb && (this.Tb = this.wb.reduce(((t, i) => (t[i.position] || (t[i.position] = true), t)), { inBar: false, aboveBar: false, belowBar: false, atPriceTop: false, atPriceBottom: false, atPriceMiddle: false })), this.Tb;
    }
    Vb() {
      if (!this.Db || !this.Vp || !this.ge) return;
      const t = this.Vp.timeScale(), i = this.ge?.data();
      if (null == t.getVisibleLogicalRange() || !this.ge || 0 === i.length) return void (this.Cb = []);
      const s = t.timeToIndex(u(i[0].time), true);
      this.Cb = this.wb.map(((i2, n) => {
        const e3 = t.timeToIndex(i2.time, true), r2 = e3 < s ? 1 : -1, h2 = u(this.ge).dataByIndex(e3, r2), a2 = { time: t.timeToIndex(u(h2).time, false), position: i2.position, shape: i2.shape, color: i2.color, id: i2.id, xb: n, text: i2.text, size: i2.size, price: i2.price, yw: i2.time };
        if ("atPriceTop" === i2.position || "atPriceBottom" === i2.position || "atPriceMiddle" === i2.position) {
          if (void 0 === i2.price) throw new Error(`Price is required for position ${i2.position}`);
          return { ...a2, position: i2.position, price: i2.price };
        }
        return { ...a2, position: i2.position, price: i2.price };
      })), this.Db = false;
    }
    Ib(t) {
      this.sh && (this.Vb(), this.sh.bb(this.Cb), this.sh.Sb(this.Ps), this.sh.yt(t));
    }
    Tg(t) {
      this.Db = true, this.jM();
    }
  };
  var _r = class extends je {
    constructor(t, i, s) {
      super(t, i), s && this.setMarkers(s);
    }
    setMarkers(t) {
      this.ah.bb(t);
    }
    markers() {
      return this.ah.Bb();
    }
  };
  function ur(t, i, s) {
    const n = new _r(t, new or(s ?? {}));
    return i && n.setMarkers(i), n;
  }
  var br = { ...e, color: "#2196f3" };

  // node_modules/d3-array/src/ascending.js
  function ascending(a2, b2) {
    return a2 == null || b2 == null ? NaN : a2 < b2 ? -1 : a2 > b2 ? 1 : a2 >= b2 ? 0 : NaN;
  }

  // node_modules/d3-array/src/descending.js
  function descending(a2, b2) {
    return a2 == null || b2 == null ? NaN : b2 < a2 ? -1 : b2 > a2 ? 1 : b2 >= a2 ? 0 : NaN;
  }

  // node_modules/d3-array/src/bisector.js
  function bisector(f2) {
    let compare1, compare2, delta;
    if (f2.length !== 2) {
      compare1 = ascending;
      compare2 = (d2, x3) => ascending(f2(d2), x3);
      delta = (d2, x3) => f2(d2) - x3;
    } else {
      compare1 = f2 === ascending || f2 === descending ? f2 : zero;
      compare2 = f2;
      delta = f2;
    }
    function left(a2, x3, lo = 0, hi2 = a2.length) {
      if (lo < hi2) {
        if (compare1(x3, x3) !== 0) return hi2;
        do {
          const mid = lo + hi2 >>> 1;
          if (compare2(a2[mid], x3) < 0) lo = mid + 1;
          else hi2 = mid;
        } while (lo < hi2);
      }
      return lo;
    }
    function right(a2, x3, lo = 0, hi2 = a2.length) {
      if (lo < hi2) {
        if (compare1(x3, x3) !== 0) return hi2;
        do {
          const mid = lo + hi2 >>> 1;
          if (compare2(a2[mid], x3) <= 0) lo = mid + 1;
          else hi2 = mid;
        } while (lo < hi2);
      }
      return lo;
    }
    function center(a2, x3, lo = 0, hi2 = a2.length) {
      const i = left(a2, x3, lo, hi2 - 1);
      return i > lo && delta(a2[i - 1], x3) > -delta(a2[i], x3) ? i - 1 : i;
    }
    return { left, center, right };
  }
  function zero() {
    return 0;
  }

  // node_modules/d3-array/src/number.js
  function number(x3) {
    return x3 === null ? NaN : +x3;
  }

  // node_modules/d3-array/src/bisect.js
  var ascendingBisect = bisector(ascending);
  var bisectRight = ascendingBisect.right;
  var bisectLeft = ascendingBisect.left;
  var bisectCenter = bisector(number).center;
  var bisect_default = bisectRight;

  // node_modules/d3-array/src/ticks.js
  var e10 = Math.sqrt(50);
  var e5 = Math.sqrt(10);
  var e2 = Math.sqrt(2);
  function tickSpec(start, stop, count) {
    const step = (stop - start) / Math.max(0, count), power = Math.floor(Math.log10(step)), error = step / Math.pow(10, power), factor = error >= e10 ? 10 : error >= e5 ? 5 : error >= e2 ? 2 : 1;
    let i1, i2, inc;
    if (power < 0) {
      inc = Math.pow(10, -power) / factor;
      i1 = Math.round(start * inc);
      i2 = Math.round(stop * inc);
      if (i1 / inc < start) ++i1;
      if (i2 / inc > stop) --i2;
      inc = -inc;
    } else {
      inc = Math.pow(10, power) * factor;
      i1 = Math.round(start / inc);
      i2 = Math.round(stop / inc);
      if (i1 * inc < start) ++i1;
      if (i2 * inc > stop) --i2;
    }
    if (i2 < i1 && 0.5 <= count && count < 2) return tickSpec(start, stop, count * 2);
    return [i1, i2, inc];
  }
  function ticks(start, stop, count) {
    stop = +stop, start = +start, count = +count;
    if (!(count > 0)) return [];
    if (start === stop) return [start];
    const reverse = stop < start, [i1, i2, inc] = reverse ? tickSpec(stop, start, count) : tickSpec(start, stop, count);
    if (!(i2 >= i1)) return [];
    const n = i2 - i1 + 1, ticks2 = new Array(n);
    if (reverse) {
      if (inc < 0) for (let i = 0; i < n; ++i) ticks2[i] = (i2 - i) / -inc;
      else for (let i = 0; i < n; ++i) ticks2[i] = (i2 - i) * inc;
    } else {
      if (inc < 0) for (let i = 0; i < n; ++i) ticks2[i] = (i1 + i) / -inc;
      else for (let i = 0; i < n; ++i) ticks2[i] = (i1 + i) * inc;
    }
    return ticks2;
  }
  function tickIncrement(start, stop, count) {
    stop = +stop, start = +start, count = +count;
    return tickSpec(start, stop, count)[2];
  }
  function tickStep(start, stop, count) {
    stop = +stop, start = +start, count = +count;
    const reverse = stop < start, inc = reverse ? tickIncrement(stop, start, count) : tickIncrement(start, stop, count);
    return (reverse ? -1 : 1) * (inc < 0 ? 1 / -inc : inc);
  }

  // node_modules/d3-scale/src/init.js
  function initRange(domain, range) {
    switch (arguments.length) {
      case 0:
        break;
      case 1:
        this.range(domain);
        break;
      default:
        this.range(range).domain(domain);
        break;
    }
    return this;
  }

  // node_modules/d3-color/src/define.js
  function define_default(constructor, factory, prototype) {
    constructor.prototype = factory.prototype = prototype;
    prototype.constructor = constructor;
  }
  function extend(parent, definition) {
    var prototype = Object.create(parent.prototype);
    for (var key in definition) prototype[key] = definition[key];
    return prototype;
  }

  // node_modules/d3-color/src/color.js
  function Color() {
  }
  var darker = 0.7;
  var brighter = 1 / darker;
  var reI = "\\s*([+-]?\\d+)\\s*";
  var reN = "\\s*([+-]?(?:\\d*\\.)?\\d+(?:[eE][+-]?\\d+)?)\\s*";
  var reP = "\\s*([+-]?(?:\\d*\\.)?\\d+(?:[eE][+-]?\\d+)?)%\\s*";
  var reHex = /^#([0-9a-f]{3,8})$/;
  var reRgbInteger = new RegExp(`^rgb\\(${reI},${reI},${reI}\\)$`);
  var reRgbPercent = new RegExp(`^rgb\\(${reP},${reP},${reP}\\)$`);
  var reRgbaInteger = new RegExp(`^rgba\\(${reI},${reI},${reI},${reN}\\)$`);
  var reRgbaPercent = new RegExp(`^rgba\\(${reP},${reP},${reP},${reN}\\)$`);
  var reHslPercent = new RegExp(`^hsl\\(${reN},${reP},${reP}\\)$`);
  var reHslaPercent = new RegExp(`^hsla\\(${reN},${reP},${reP},${reN}\\)$`);
  var named = {
    aliceblue: 15792383,
    antiquewhite: 16444375,
    aqua: 65535,
    aquamarine: 8388564,
    azure: 15794175,
    beige: 16119260,
    bisque: 16770244,
    black: 0,
    blanchedalmond: 16772045,
    blue: 255,
    blueviolet: 9055202,
    brown: 10824234,
    burlywood: 14596231,
    cadetblue: 6266528,
    chartreuse: 8388352,
    chocolate: 13789470,
    coral: 16744272,
    cornflowerblue: 6591981,
    cornsilk: 16775388,
    crimson: 14423100,
    cyan: 65535,
    darkblue: 139,
    darkcyan: 35723,
    darkgoldenrod: 12092939,
    darkgray: 11119017,
    darkgreen: 25600,
    darkgrey: 11119017,
    darkkhaki: 12433259,
    darkmagenta: 9109643,
    darkolivegreen: 5597999,
    darkorange: 16747520,
    darkorchid: 10040012,
    darkred: 9109504,
    darksalmon: 15308410,
    darkseagreen: 9419919,
    darkslateblue: 4734347,
    darkslategray: 3100495,
    darkslategrey: 3100495,
    darkturquoise: 52945,
    darkviolet: 9699539,
    deeppink: 16716947,
    deepskyblue: 49151,
    dimgray: 6908265,
    dimgrey: 6908265,
    dodgerblue: 2003199,
    firebrick: 11674146,
    floralwhite: 16775920,
    forestgreen: 2263842,
    fuchsia: 16711935,
    gainsboro: 14474460,
    ghostwhite: 16316671,
    gold: 16766720,
    goldenrod: 14329120,
    gray: 8421504,
    green: 32768,
    greenyellow: 11403055,
    grey: 8421504,
    honeydew: 15794160,
    hotpink: 16738740,
    indianred: 13458524,
    indigo: 4915330,
    ivory: 16777200,
    khaki: 15787660,
    lavender: 15132410,
    lavenderblush: 16773365,
    lawngreen: 8190976,
    lemonchiffon: 16775885,
    lightblue: 11393254,
    lightcoral: 15761536,
    lightcyan: 14745599,
    lightgoldenrodyellow: 16448210,
    lightgray: 13882323,
    lightgreen: 9498256,
    lightgrey: 13882323,
    lightpink: 16758465,
    lightsalmon: 16752762,
    lightseagreen: 2142890,
    lightskyblue: 8900346,
    lightslategray: 7833753,
    lightslategrey: 7833753,
    lightsteelblue: 11584734,
    lightyellow: 16777184,
    lime: 65280,
    limegreen: 3329330,
    linen: 16445670,
    magenta: 16711935,
    maroon: 8388608,
    mediumaquamarine: 6737322,
    mediumblue: 205,
    mediumorchid: 12211667,
    mediumpurple: 9662683,
    mediumseagreen: 3978097,
    mediumslateblue: 8087790,
    mediumspringgreen: 64154,
    mediumturquoise: 4772300,
    mediumvioletred: 13047173,
    midnightblue: 1644912,
    mintcream: 16121850,
    mistyrose: 16770273,
    moccasin: 16770229,
    navajowhite: 16768685,
    navy: 128,
    oldlace: 16643558,
    olive: 8421376,
    olivedrab: 7048739,
    orange: 16753920,
    orangered: 16729344,
    orchid: 14315734,
    palegoldenrod: 15657130,
    palegreen: 10025880,
    paleturquoise: 11529966,
    palevioletred: 14381203,
    papayawhip: 16773077,
    peachpuff: 16767673,
    peru: 13468991,
    pink: 16761035,
    plum: 14524637,
    powderblue: 11591910,
    purple: 8388736,
    rebeccapurple: 6697881,
    red: 16711680,
    rosybrown: 12357519,
    royalblue: 4286945,
    saddlebrown: 9127187,
    salmon: 16416882,
    sandybrown: 16032864,
    seagreen: 3050327,
    seashell: 16774638,
    sienna: 10506797,
    silver: 12632256,
    skyblue: 8900331,
    slateblue: 6970061,
    slategray: 7372944,
    slategrey: 7372944,
    snow: 16775930,
    springgreen: 65407,
    steelblue: 4620980,
    tan: 13808780,
    teal: 32896,
    thistle: 14204888,
    tomato: 16737095,
    turquoise: 4251856,
    violet: 15631086,
    wheat: 16113331,
    white: 16777215,
    whitesmoke: 16119285,
    yellow: 16776960,
    yellowgreen: 10145074
  };
  define_default(Color, color, {
    copy(channels) {
      return Object.assign(new this.constructor(), this, channels);
    },
    displayable() {
      return this.rgb().displayable();
    },
    hex: color_formatHex,
    // Deprecated! Use color.formatHex.
    formatHex: color_formatHex,
    formatHex8: color_formatHex8,
    formatHsl: color_formatHsl,
    formatRgb: color_formatRgb,
    toString: color_formatRgb
  });
  function color_formatHex() {
    return this.rgb().formatHex();
  }
  function color_formatHex8() {
    return this.rgb().formatHex8();
  }
  function color_formatHsl() {
    return hslConvert(this).formatHsl();
  }
  function color_formatRgb() {
    return this.rgb().formatRgb();
  }
  function color(format2) {
    var m2, l2;
    format2 = (format2 + "").trim().toLowerCase();
    return (m2 = reHex.exec(format2)) ? (l2 = m2[1].length, m2 = parseInt(m2[1], 16), l2 === 6 ? rgbn(m2) : l2 === 3 ? new Rgb(m2 >> 8 & 15 | m2 >> 4 & 240, m2 >> 4 & 15 | m2 & 240, (m2 & 15) << 4 | m2 & 15, 1) : l2 === 8 ? rgba(m2 >> 24 & 255, m2 >> 16 & 255, m2 >> 8 & 255, (m2 & 255) / 255) : l2 === 4 ? rgba(m2 >> 12 & 15 | m2 >> 8 & 240, m2 >> 8 & 15 | m2 >> 4 & 240, m2 >> 4 & 15 | m2 & 240, ((m2 & 15) << 4 | m2 & 15) / 255) : null) : (m2 = reRgbInteger.exec(format2)) ? new Rgb(m2[1], m2[2], m2[3], 1) : (m2 = reRgbPercent.exec(format2)) ? new Rgb(m2[1] * 255 / 100, m2[2] * 255 / 100, m2[3] * 255 / 100, 1) : (m2 = reRgbaInteger.exec(format2)) ? rgba(m2[1], m2[2], m2[3], m2[4]) : (m2 = reRgbaPercent.exec(format2)) ? rgba(m2[1] * 255 / 100, m2[2] * 255 / 100, m2[3] * 255 / 100, m2[4]) : (m2 = reHslPercent.exec(format2)) ? hsla(m2[1], m2[2] / 100, m2[3] / 100, 1) : (m2 = reHslaPercent.exec(format2)) ? hsla(m2[1], m2[2] / 100, m2[3] / 100, m2[4]) : named.hasOwnProperty(format2) ? rgbn(named[format2]) : format2 === "transparent" ? new Rgb(NaN, NaN, NaN, 0) : null;
  }
  function rgbn(n) {
    return new Rgb(n >> 16 & 255, n >> 8 & 255, n & 255, 1);
  }
  function rgba(r2, g2, b2, a2) {
    if (a2 <= 0) r2 = g2 = b2 = NaN;
    return new Rgb(r2, g2, b2, a2);
  }
  function rgbConvert(o2) {
    if (!(o2 instanceof Color)) o2 = color(o2);
    if (!o2) return new Rgb();
    o2 = o2.rgb();
    return new Rgb(o2.r, o2.g, o2.b, o2.opacity);
  }
  function rgb(r2, g2, b2, opacity) {
    return arguments.length === 1 ? rgbConvert(r2) : new Rgb(r2, g2, b2, opacity == null ? 1 : opacity);
  }
  function Rgb(r2, g2, b2, opacity) {
    this.r = +r2;
    this.g = +g2;
    this.b = +b2;
    this.opacity = +opacity;
  }
  define_default(Rgb, rgb, extend(Color, {
    brighter(k2) {
      k2 = k2 == null ? brighter : Math.pow(brighter, k2);
      return new Rgb(this.r * k2, this.g * k2, this.b * k2, this.opacity);
    },
    darker(k2) {
      k2 = k2 == null ? darker : Math.pow(darker, k2);
      return new Rgb(this.r * k2, this.g * k2, this.b * k2, this.opacity);
    },
    rgb() {
      return this;
    },
    clamp() {
      return new Rgb(clampi(this.r), clampi(this.g), clampi(this.b), clampa(this.opacity));
    },
    displayable() {
      return -0.5 <= this.r && this.r < 255.5 && (-0.5 <= this.g && this.g < 255.5) && (-0.5 <= this.b && this.b < 255.5) && (0 <= this.opacity && this.opacity <= 1);
    },
    hex: rgb_formatHex,
    // Deprecated! Use color.formatHex.
    formatHex: rgb_formatHex,
    formatHex8: rgb_formatHex8,
    formatRgb: rgb_formatRgb,
    toString: rgb_formatRgb
  }));
  function rgb_formatHex() {
    return `#${hex(this.r)}${hex(this.g)}${hex(this.b)}`;
  }
  function rgb_formatHex8() {
    return `#${hex(this.r)}${hex(this.g)}${hex(this.b)}${hex((isNaN(this.opacity) ? 1 : this.opacity) * 255)}`;
  }
  function rgb_formatRgb() {
    const a2 = clampa(this.opacity);
    return `${a2 === 1 ? "rgb(" : "rgba("}${clampi(this.r)}, ${clampi(this.g)}, ${clampi(this.b)}${a2 === 1 ? ")" : `, ${a2})`}`;
  }
  function clampa(opacity) {
    return isNaN(opacity) ? 1 : Math.max(0, Math.min(1, opacity));
  }
  function clampi(value) {
    return Math.max(0, Math.min(255, Math.round(value) || 0));
  }
  function hex(value) {
    value = clampi(value);
    return (value < 16 ? "0" : "") + value.toString(16);
  }
  function hsla(h2, s, l2, a2) {
    if (a2 <= 0) h2 = s = l2 = NaN;
    else if (l2 <= 0 || l2 >= 1) h2 = s = NaN;
    else if (s <= 0) h2 = NaN;
    return new Hsl(h2, s, l2, a2);
  }
  function hslConvert(o2) {
    if (o2 instanceof Hsl) return new Hsl(o2.h, o2.s, o2.l, o2.opacity);
    if (!(o2 instanceof Color)) o2 = color(o2);
    if (!o2) return new Hsl();
    if (o2 instanceof Hsl) return o2;
    o2 = o2.rgb();
    var r2 = o2.r / 255, g2 = o2.g / 255, b2 = o2.b / 255, min = Math.min(r2, g2, b2), max = Math.max(r2, g2, b2), h2 = NaN, s = max - min, l2 = (max + min) / 2;
    if (s) {
      if (r2 === max) h2 = (g2 - b2) / s + (g2 < b2) * 6;
      else if (g2 === max) h2 = (b2 - r2) / s + 2;
      else h2 = (r2 - g2) / s + 4;
      s /= l2 < 0.5 ? max + min : 2 - max - min;
      h2 *= 60;
    } else {
      s = l2 > 0 && l2 < 1 ? 0 : h2;
    }
    return new Hsl(h2, s, l2, o2.opacity);
  }
  function hsl(h2, s, l2, opacity) {
    return arguments.length === 1 ? hslConvert(h2) : new Hsl(h2, s, l2, opacity == null ? 1 : opacity);
  }
  function Hsl(h2, s, l2, opacity) {
    this.h = +h2;
    this.s = +s;
    this.l = +l2;
    this.opacity = +opacity;
  }
  define_default(Hsl, hsl, extend(Color, {
    brighter(k2) {
      k2 = k2 == null ? brighter : Math.pow(brighter, k2);
      return new Hsl(this.h, this.s, this.l * k2, this.opacity);
    },
    darker(k2) {
      k2 = k2 == null ? darker : Math.pow(darker, k2);
      return new Hsl(this.h, this.s, this.l * k2, this.opacity);
    },
    rgb() {
      var h2 = this.h % 360 + (this.h < 0) * 360, s = isNaN(h2) || isNaN(this.s) ? 0 : this.s, l2 = this.l, m2 = l2 + (l2 < 0.5 ? l2 : 1 - l2) * s, m1 = 2 * l2 - m2;
      return new Rgb(
        hsl2rgb(h2 >= 240 ? h2 - 240 : h2 + 120, m1, m2),
        hsl2rgb(h2, m1, m2),
        hsl2rgb(h2 < 120 ? h2 + 240 : h2 - 120, m1, m2),
        this.opacity
      );
    },
    clamp() {
      return new Hsl(clamph(this.h), clampt(this.s), clampt(this.l), clampa(this.opacity));
    },
    displayable() {
      return (0 <= this.s && this.s <= 1 || isNaN(this.s)) && (0 <= this.l && this.l <= 1) && (0 <= this.opacity && this.opacity <= 1);
    },
    formatHsl() {
      const a2 = clampa(this.opacity);
      return `${a2 === 1 ? "hsl(" : "hsla("}${clamph(this.h)}, ${clampt(this.s) * 100}%, ${clampt(this.l) * 100}%${a2 === 1 ? ")" : `, ${a2})`}`;
    }
  }));
  function clamph(value) {
    value = (value || 0) % 360;
    return value < 0 ? value + 360 : value;
  }
  function clampt(value) {
    return Math.max(0, Math.min(1, value || 0));
  }
  function hsl2rgb(h2, m1, m2) {
    return (h2 < 60 ? m1 + (m2 - m1) * h2 / 60 : h2 < 180 ? m2 : h2 < 240 ? m1 + (m2 - m1) * (240 - h2) / 60 : m1) * 255;
  }

  // node_modules/d3-interpolate/src/basis.js
  function basis(t12, v0, v1, v2, v3) {
    var t2 = t12 * t12, t3 = t2 * t12;
    return ((1 - 3 * t12 + 3 * t2 - t3) * v0 + (4 - 6 * t2 + 3 * t3) * v1 + (1 + 3 * t12 + 3 * t2 - 3 * t3) * v2 + t3 * v3) / 6;
  }
  function basis_default(values) {
    var n = values.length - 1;
    return function(t) {
      var i = t <= 0 ? t = 0 : t >= 1 ? (t = 1, n - 1) : Math.floor(t * n), v1 = values[i], v2 = values[i + 1], v0 = i > 0 ? values[i - 1] : 2 * v1 - v2, v3 = i < n - 1 ? values[i + 2] : 2 * v2 - v1;
      return basis((t - i / n) * n, v0, v1, v2, v3);
    };
  }

  // node_modules/d3-interpolate/src/basisClosed.js
  function basisClosed_default(values) {
    var n = values.length;
    return function(t) {
      var i = Math.floor(((t %= 1) < 0 ? ++t : t) * n), v0 = values[(i + n - 1) % n], v1 = values[i % n], v2 = values[(i + 1) % n], v3 = values[(i + 2) % n];
      return basis((t - i / n) * n, v0, v1, v2, v3);
    };
  }

  // node_modules/d3-interpolate/src/constant.js
  var constant_default = (x3) => () => x3;

  // node_modules/d3-interpolate/src/color.js
  function linear(a2, d2) {
    return function(t) {
      return a2 + t * d2;
    };
  }
  function exponential(a2, b2, y3) {
    return a2 = Math.pow(a2, y3), b2 = Math.pow(b2, y3) - a2, y3 = 1 / y3, function(t) {
      return Math.pow(a2 + t * b2, y3);
    };
  }
  function gamma(y3) {
    return (y3 = +y3) === 1 ? nogamma : function(a2, b2) {
      return b2 - a2 ? exponential(a2, b2, y3) : constant_default(isNaN(a2) ? b2 : a2);
    };
  }
  function nogamma(a2, b2) {
    var d2 = b2 - a2;
    return d2 ? linear(a2, d2) : constant_default(isNaN(a2) ? b2 : a2);
  }

  // node_modules/d3-interpolate/src/rgb.js
  var rgb_default = (function rgbGamma(y3) {
    var color2 = gamma(y3);
    function rgb2(start, end) {
      var r2 = color2((start = rgb(start)).r, (end = rgb(end)).r), g2 = color2(start.g, end.g), b2 = color2(start.b, end.b), opacity = nogamma(start.opacity, end.opacity);
      return function(t) {
        start.r = r2(t);
        start.g = g2(t);
        start.b = b2(t);
        start.opacity = opacity(t);
        return start + "";
      };
    }
    rgb2.gamma = rgbGamma;
    return rgb2;
  })(1);
  function rgbSpline(spline) {
    return function(colors) {
      var n = colors.length, r2 = new Array(n), g2 = new Array(n), b2 = new Array(n), i, color2;
      for (i = 0; i < n; ++i) {
        color2 = rgb(colors[i]);
        r2[i] = color2.r || 0;
        g2[i] = color2.g || 0;
        b2[i] = color2.b || 0;
      }
      r2 = spline(r2);
      g2 = spline(g2);
      b2 = spline(b2);
      color2.opacity = 1;
      return function(t) {
        color2.r = r2(t);
        color2.g = g2(t);
        color2.b = b2(t);
        return color2 + "";
      };
    };
  }
  var rgbBasis = rgbSpline(basis_default);
  var rgbBasisClosed = rgbSpline(basisClosed_default);

  // node_modules/d3-interpolate/src/numberArray.js
  function numberArray_default(a2, b2) {
    if (!b2) b2 = [];
    var n = a2 ? Math.min(b2.length, a2.length) : 0, c2 = b2.slice(), i;
    return function(t) {
      for (i = 0; i < n; ++i) c2[i] = a2[i] * (1 - t) + b2[i] * t;
      return c2;
    };
  }
  function isNumberArray(x3) {
    return ArrayBuffer.isView(x3) && !(x3 instanceof DataView);
  }

  // node_modules/d3-interpolate/src/array.js
  function genericArray(a2, b2) {
    var nb = b2 ? b2.length : 0, na = a2 ? Math.min(nb, a2.length) : 0, x3 = new Array(na), c2 = new Array(nb), i;
    for (i = 0; i < na; ++i) x3[i] = value_default(a2[i], b2[i]);
    for (; i < nb; ++i) c2[i] = b2[i];
    return function(t) {
      for (i = 0; i < na; ++i) c2[i] = x3[i](t);
      return c2;
    };
  }

  // node_modules/d3-interpolate/src/date.js
  function date_default(a2, b2) {
    var d2 = /* @__PURE__ */ new Date();
    return a2 = +a2, b2 = +b2, function(t) {
      return d2.setTime(a2 * (1 - t) + b2 * t), d2;
    };
  }

  // node_modules/d3-interpolate/src/number.js
  function number_default(a2, b2) {
    return a2 = +a2, b2 = +b2, function(t) {
      return a2 * (1 - t) + b2 * t;
    };
  }

  // node_modules/d3-interpolate/src/object.js
  function object_default(a2, b2) {
    var i = {}, c2 = {}, k2;
    if (a2 === null || typeof a2 !== "object") a2 = {};
    if (b2 === null || typeof b2 !== "object") b2 = {};
    for (k2 in b2) {
      if (k2 in a2) {
        i[k2] = value_default(a2[k2], b2[k2]);
      } else {
        c2[k2] = b2[k2];
      }
    }
    return function(t) {
      for (k2 in i) c2[k2] = i[k2](t);
      return c2;
    };
  }

  // node_modules/d3-interpolate/src/string.js
  var reA = /[-+]?(?:\d+\.?\d*|\.?\d+)(?:[eE][-+]?\d+)?/g;
  var reB = new RegExp(reA.source, "g");
  function zero2(b2) {
    return function() {
      return b2;
    };
  }
  function one(b2) {
    return function(t) {
      return b2(t) + "";
    };
  }
  function string_default(a2, b2) {
    var bi2 = reA.lastIndex = reB.lastIndex = 0, am, bm, bs2, i = -1, s = [], q2 = [];
    a2 = a2 + "", b2 = b2 + "";
    while ((am = reA.exec(a2)) && (bm = reB.exec(b2))) {
      if ((bs2 = bm.index) > bi2) {
        bs2 = b2.slice(bi2, bs2);
        if (s[i]) s[i] += bs2;
        else s[++i] = bs2;
      }
      if ((am = am[0]) === (bm = bm[0])) {
        if (s[i]) s[i] += bm;
        else s[++i] = bm;
      } else {
        s[++i] = null;
        q2.push({ i, x: number_default(am, bm) });
      }
      bi2 = reB.lastIndex;
    }
    if (bi2 < b2.length) {
      bs2 = b2.slice(bi2);
      if (s[i]) s[i] += bs2;
      else s[++i] = bs2;
    }
    return s.length < 2 ? q2[0] ? one(q2[0].x) : zero2(b2) : (b2 = q2.length, function(t) {
      for (var i2 = 0, o2; i2 < b2; ++i2) s[(o2 = q2[i2]).i] = o2.x(t);
      return s.join("");
    });
  }

  // node_modules/d3-interpolate/src/value.js
  function value_default(a2, b2) {
    var t = typeof b2, c2;
    return b2 == null || t === "boolean" ? constant_default(b2) : (t === "number" ? number_default : t === "string" ? (c2 = color(b2)) ? (b2 = c2, rgb_default) : string_default : b2 instanceof color ? rgb_default : b2 instanceof Date ? date_default : isNumberArray(b2) ? numberArray_default : Array.isArray(b2) ? genericArray : typeof b2.valueOf !== "function" && typeof b2.toString !== "function" || isNaN(b2) ? object_default : number_default)(a2, b2);
  }

  // node_modules/d3-interpolate/src/round.js
  function round_default(a2, b2) {
    return a2 = +a2, b2 = +b2, function(t) {
      return Math.round(a2 * (1 - t) + b2 * t);
    };
  }

  // node_modules/d3-scale/src/constant.js
  function constants(x3) {
    return function() {
      return x3;
    };
  }

  // node_modules/d3-scale/src/number.js
  function number2(x3) {
    return +x3;
  }

  // node_modules/d3-scale/src/continuous.js
  var unit = [0, 1];
  function identity(x3) {
    return x3;
  }
  function normalize(a2, b2) {
    return (b2 -= a2 = +a2) ? function(x3) {
      return (x3 - a2) / b2;
    } : constants(isNaN(b2) ? NaN : 0.5);
  }
  function clamper(a2, b2) {
    var t;
    if (a2 > b2) t = a2, a2 = b2, b2 = t;
    return function(x3) {
      return Math.max(a2, Math.min(b2, x3));
    };
  }
  function bimap(domain, range, interpolate) {
    var d0 = domain[0], d1 = domain[1], r0 = range[0], r1 = range[1];
    if (d1 < d0) d0 = normalize(d1, d0), r0 = interpolate(r1, r0);
    else d0 = normalize(d0, d1), r0 = interpolate(r0, r1);
    return function(x3) {
      return r0(d0(x3));
    };
  }
  function polymap(domain, range, interpolate) {
    var j2 = Math.min(domain.length, range.length) - 1, d2 = new Array(j2), r2 = new Array(j2), i = -1;
    if (domain[j2] < domain[0]) {
      domain = domain.slice().reverse();
      range = range.slice().reverse();
    }
    while (++i < j2) {
      d2[i] = normalize(domain[i], domain[i + 1]);
      r2[i] = interpolate(range[i], range[i + 1]);
    }
    return function(x3) {
      var i2 = bisect_default(domain, x3, 1, j2) - 1;
      return r2[i2](d2[i2](x3));
    };
  }
  function copy(source, target) {
    return target.domain(source.domain()).range(source.range()).interpolate(source.interpolate()).clamp(source.clamp()).unknown(source.unknown());
  }
  function transformer() {
    var domain = unit, range = unit, interpolate = value_default, transform, untransform, unknown, clamp = identity, piecewise, output, input;
    function rescale() {
      var n = Math.min(domain.length, range.length);
      if (clamp !== identity) clamp = clamper(domain[0], domain[n - 1]);
      piecewise = n > 2 ? polymap : bimap;
      output = input = null;
      return scale;
    }
    function scale(x3) {
      return x3 == null || isNaN(x3 = +x3) ? unknown : (output || (output = piecewise(domain.map(transform), range, interpolate)))(transform(clamp(x3)));
    }
    scale.invert = function(y3) {
      return clamp(untransform((input || (input = piecewise(range, domain.map(transform), number_default)))(y3)));
    };
    scale.domain = function(_2) {
      return arguments.length ? (domain = Array.from(_2, number2), rescale()) : domain.slice();
    };
    scale.range = function(_2) {
      return arguments.length ? (range = Array.from(_2), rescale()) : range.slice();
    };
    scale.rangeRound = function(_2) {
      return range = Array.from(_2), interpolate = round_default, rescale();
    };
    scale.clamp = function(_2) {
      return arguments.length ? (clamp = _2 ? true : identity, rescale()) : clamp !== identity;
    };
    scale.interpolate = function(_2) {
      return arguments.length ? (interpolate = _2, rescale()) : interpolate;
    };
    scale.unknown = function(_2) {
      return arguments.length ? (unknown = _2, scale) : unknown;
    };
    return function(t, u2) {
      transform = t, untransform = u2;
      return rescale();
    };
  }
  function continuous() {
    return transformer()(identity, identity);
  }

  // node_modules/d3-format/src/formatDecimal.js
  function formatDecimal_default(x3) {
    return Math.abs(x3 = Math.round(x3)) >= 1e21 ? x3.toLocaleString("en").replace(/,/g, "") : x3.toString(10);
  }
  function formatDecimalParts(x3, p2) {
    if (!isFinite(x3) || x3 === 0) return null;
    var i = (x3 = p2 ? x3.toExponential(p2 - 1) : x3.toExponential()).indexOf("e"), coefficient = x3.slice(0, i);
    return [
      coefficient.length > 1 ? coefficient[0] + coefficient.slice(2) : coefficient,
      +x3.slice(i + 1)
    ];
  }

  // node_modules/d3-format/src/exponent.js
  function exponent_default(x3) {
    return x3 = formatDecimalParts(Math.abs(x3)), x3 ? x3[1] : NaN;
  }

  // node_modules/d3-format/src/formatGroup.js
  function formatGroup_default(grouping, thousands) {
    return function(value, width) {
      var i = value.length, t = [], j2 = 0, g2 = grouping[0], length = 0;
      while (i > 0 && g2 > 0) {
        if (length + g2 + 1 > width) g2 = Math.max(1, width - length);
        t.push(value.substring(i -= g2, i + g2));
        if ((length += g2 + 1) > width) break;
        g2 = grouping[j2 = (j2 + 1) % grouping.length];
      }
      return t.reverse().join(thousands);
    };
  }

  // node_modules/d3-format/src/formatNumerals.js
  function formatNumerals_default(numerals) {
    return function(value) {
      return value.replace(/[0-9]/g, function(i) {
        return numerals[+i];
      });
    };
  }

  // node_modules/d3-format/src/formatSpecifier.js
  var re = /^(?:(.)?([<>=^]))?([+\-( ])?([$#])?(0)?(\d+)?(,)?(\.\d+)?(~)?([a-z%])?$/i;
  function formatSpecifier(specifier) {
    if (!(match = re.exec(specifier))) throw new Error("invalid format: " + specifier);
    var match;
    return new FormatSpecifier({
      fill: match[1],
      align: match[2],
      sign: match[3],
      symbol: match[4],
      zero: match[5],
      width: match[6],
      comma: match[7],
      precision: match[8] && match[8].slice(1),
      trim: match[9],
      type: match[10]
    });
  }
  formatSpecifier.prototype = FormatSpecifier.prototype;
  function FormatSpecifier(specifier) {
    this.fill = specifier.fill === void 0 ? " " : specifier.fill + "";
    this.align = specifier.align === void 0 ? ">" : specifier.align + "";
    this.sign = specifier.sign === void 0 ? "-" : specifier.sign + "";
    this.symbol = specifier.symbol === void 0 ? "" : specifier.symbol + "";
    this.zero = !!specifier.zero;
    this.width = specifier.width === void 0 ? void 0 : +specifier.width;
    this.comma = !!specifier.comma;
    this.precision = specifier.precision === void 0 ? void 0 : +specifier.precision;
    this.trim = !!specifier.trim;
    this.type = specifier.type === void 0 ? "" : specifier.type + "";
  }
  FormatSpecifier.prototype.toString = function() {
    return this.fill + this.align + this.sign + this.symbol + (this.zero ? "0" : "") + (this.width === void 0 ? "" : Math.max(1, this.width | 0)) + (this.comma ? "," : "") + (this.precision === void 0 ? "" : "." + Math.max(0, this.precision | 0)) + (this.trim ? "~" : "") + this.type;
  };

  // node_modules/d3-format/src/formatTrim.js
  function formatTrim_default(s) {
    out: for (var n = s.length, i = 1, i0 = -1, i1; i < n; ++i) {
      switch (s[i]) {
        case ".":
          i0 = i1 = i;
          break;
        case "0":
          if (i0 === 0) i0 = i;
          i1 = i;
          break;
        default:
          if (!+s[i]) break out;
          if (i0 > 0) i0 = 0;
          break;
      }
    }
    return i0 > 0 ? s.slice(0, i0) + s.slice(i1 + 1) : s;
  }

  // node_modules/d3-format/src/formatPrefixAuto.js
  var prefixExponent;
  function formatPrefixAuto_default(x3, p2) {
    var d2 = formatDecimalParts(x3, p2);
    if (!d2) return prefixExponent = void 0, x3.toPrecision(p2);
    var coefficient = d2[0], exponent = d2[1], i = exponent - (prefixExponent = Math.max(-8, Math.min(8, Math.floor(exponent / 3))) * 3) + 1, n = coefficient.length;
    return i === n ? coefficient : i > n ? coefficient + new Array(i - n + 1).join("0") : i > 0 ? coefficient.slice(0, i) + "." + coefficient.slice(i) : "0." + new Array(1 - i).join("0") + formatDecimalParts(x3, Math.max(0, p2 + i - 1))[0];
  }

  // node_modules/d3-format/src/formatRounded.js
  function formatRounded_default(x3, p2) {
    var d2 = formatDecimalParts(x3, p2);
    if (!d2) return x3 + "";
    var coefficient = d2[0], exponent = d2[1];
    return exponent < 0 ? "0." + new Array(-exponent).join("0") + coefficient : coefficient.length > exponent + 1 ? coefficient.slice(0, exponent + 1) + "." + coefficient.slice(exponent + 1) : coefficient + new Array(exponent - coefficient.length + 2).join("0");
  }

  // node_modules/d3-format/src/formatTypes.js
  var formatTypes_default = {
    "%": (x3, p2) => (x3 * 100).toFixed(p2),
    "b": (x3) => Math.round(x3).toString(2),
    "c": (x3) => x3 + "",
    "d": formatDecimal_default,
    "e": (x3, p2) => x3.toExponential(p2),
    "f": (x3, p2) => x3.toFixed(p2),
    "g": (x3, p2) => x3.toPrecision(p2),
    "o": (x3) => Math.round(x3).toString(8),
    "p": (x3, p2) => formatRounded_default(x3 * 100, p2),
    "r": formatRounded_default,
    "s": formatPrefixAuto_default,
    "X": (x3) => Math.round(x3).toString(16).toUpperCase(),
    "x": (x3) => Math.round(x3).toString(16)
  };

  // node_modules/d3-format/src/identity.js
  function identity_default(x3) {
    return x3;
  }

  // node_modules/d3-format/src/locale.js
  var map = Array.prototype.map;
  var prefixes = ["y", "z", "a", "f", "p", "n", "\xB5", "m", "", "k", "M", "G", "T", "P", "E", "Z", "Y"];
  function locale_default(locale3) {
    var group = locale3.grouping === void 0 || locale3.thousands === void 0 ? identity_default : formatGroup_default(map.call(locale3.grouping, Number), locale3.thousands + ""), currencyPrefix = locale3.currency === void 0 ? "" : locale3.currency[0] + "", currencySuffix = locale3.currency === void 0 ? "" : locale3.currency[1] + "", decimal = locale3.decimal === void 0 ? "." : locale3.decimal + "", numerals = locale3.numerals === void 0 ? identity_default : formatNumerals_default(map.call(locale3.numerals, String)), percent = locale3.percent === void 0 ? "%" : locale3.percent + "", minus = locale3.minus === void 0 ? "\u2212" : locale3.minus + "", nan = locale3.nan === void 0 ? "NaN" : locale3.nan + "";
    function newFormat(specifier, options) {
      specifier = formatSpecifier(specifier);
      var fill = specifier.fill, align = specifier.align, sign = specifier.sign, symbol = specifier.symbol, zero3 = specifier.zero, width = specifier.width, comma = specifier.comma, precision = specifier.precision, trim = specifier.trim, type = specifier.type;
      if (type === "n") comma = true, type = "g";
      else if (!formatTypes_default[type]) precision === void 0 && (precision = 12), trim = true, type = "g";
      if (zero3 || fill === "0" && align === "=") zero3 = true, fill = "0", align = "=";
      var prefix = (options && options.prefix !== void 0 ? options.prefix : "") + (symbol === "$" ? currencyPrefix : symbol === "#" && /[boxX]/.test(type) ? "0" + type.toLowerCase() : ""), suffix = (symbol === "$" ? currencySuffix : /[%p]/.test(type) ? percent : "") + (options && options.suffix !== void 0 ? options.suffix : "");
      var formatType = formatTypes_default[type], maybeSuffix = /[defgprs%]/.test(type);
      precision = precision === void 0 ? 6 : /[gprs]/.test(type) ? Math.max(1, Math.min(21, precision)) : Math.max(0, Math.min(20, precision));
      function format2(value) {
        var valuePrefix = prefix, valueSuffix = suffix, i, n, c2;
        if (type === "c") {
          valueSuffix = formatType(value) + valueSuffix;
          value = "";
        } else {
          value = +value;
          var valueNegative = value < 0 || 1 / value < 0;
          value = isNaN(value) ? nan : formatType(Math.abs(value), precision);
          if (trim) value = formatTrim_default(value);
          if (valueNegative && +value === 0 && sign !== "+") valueNegative = false;
          valuePrefix = (valueNegative ? sign === "(" ? sign : minus : sign === "-" || sign === "(" ? "" : sign) + valuePrefix;
          valueSuffix = (type === "s" && !isNaN(value) && prefixExponent !== void 0 ? prefixes[8 + prefixExponent / 3] : "") + valueSuffix + (valueNegative && sign === "(" ? ")" : "");
          if (maybeSuffix) {
            i = -1, n = value.length;
            while (++i < n) {
              if (c2 = value.charCodeAt(i), 48 > c2 || c2 > 57) {
                valueSuffix = (c2 === 46 ? decimal + value.slice(i + 1) : value.slice(i)) + valueSuffix;
                value = value.slice(0, i);
                break;
              }
            }
          }
        }
        if (comma && !zero3) value = group(value, Infinity);
        var length = valuePrefix.length + value.length + valueSuffix.length, padding = length < width ? new Array(width - length + 1).join(fill) : "";
        if (comma && zero3) value = group(padding + value, padding.length ? width - valueSuffix.length : Infinity), padding = "";
        switch (align) {
          case "<":
            value = valuePrefix + value + valueSuffix + padding;
            break;
          case "=":
            value = valuePrefix + padding + value + valueSuffix;
            break;
          case "^":
            value = padding.slice(0, length = padding.length >> 1) + valuePrefix + value + valueSuffix + padding.slice(length);
            break;
          default:
            value = padding + valuePrefix + value + valueSuffix;
            break;
        }
        return numerals(value);
      }
      format2.toString = function() {
        return specifier + "";
      };
      return format2;
    }
    function formatPrefix2(specifier, value) {
      var e3 = Math.max(-8, Math.min(8, Math.floor(exponent_default(value) / 3))) * 3, k2 = Math.pow(10, -e3), f2 = newFormat((specifier = formatSpecifier(specifier), specifier.type = "f", specifier), { suffix: prefixes[8 + e3 / 3] });
      return function(value2) {
        return f2(k2 * value2);
      };
    }
    return {
      format: newFormat,
      formatPrefix: formatPrefix2
    };
  }

  // node_modules/d3-format/src/defaultLocale.js
  var locale;
  var format;
  var formatPrefix;
  defaultLocale({
    thousands: ",",
    grouping: [3],
    currency: ["$", ""]
  });
  function defaultLocale(definition) {
    locale = locale_default(definition);
    format = locale.format;
    formatPrefix = locale.formatPrefix;
    return locale;
  }

  // node_modules/d3-format/src/precisionFixed.js
  function precisionFixed_default(step) {
    return Math.max(0, -exponent_default(Math.abs(step)));
  }

  // node_modules/d3-format/src/precisionPrefix.js
  function precisionPrefix_default(step, value) {
    return Math.max(0, Math.max(-8, Math.min(8, Math.floor(exponent_default(value) / 3))) * 3 - exponent_default(Math.abs(step)));
  }

  // node_modules/d3-format/src/precisionRound.js
  function precisionRound_default(step, max) {
    step = Math.abs(step), max = Math.abs(max) - step;
    return Math.max(0, exponent_default(max) - exponent_default(step)) + 1;
  }

  // node_modules/d3-scale/src/tickFormat.js
  function tickFormat(start, stop, count, specifier) {
    var step = tickStep(start, stop, count), precision;
    specifier = formatSpecifier(specifier == null ? ",f" : specifier);
    switch (specifier.type) {
      case "s": {
        var value = Math.max(Math.abs(start), Math.abs(stop));
        if (specifier.precision == null && !isNaN(precision = precisionPrefix_default(step, value))) specifier.precision = precision;
        return formatPrefix(specifier, value);
      }
      case "":
      case "e":
      case "g":
      case "p":
      case "r": {
        if (specifier.precision == null && !isNaN(precision = precisionRound_default(step, Math.max(Math.abs(start), Math.abs(stop))))) specifier.precision = precision - (specifier.type === "e");
        break;
      }
      case "f":
      case "%": {
        if (specifier.precision == null && !isNaN(precision = precisionFixed_default(step))) specifier.precision = precision - (specifier.type === "%") * 2;
        break;
      }
    }
    return format(specifier);
  }

  // node_modules/d3-scale/src/linear.js
  function linearish(scale) {
    var domain = scale.domain;
    scale.ticks = function(count) {
      var d2 = domain();
      return ticks(d2[0], d2[d2.length - 1], count == null ? 10 : count);
    };
    scale.tickFormat = function(count, specifier) {
      var d2 = domain();
      return tickFormat(d2[0], d2[d2.length - 1], count == null ? 10 : count, specifier);
    };
    scale.nice = function(count) {
      if (count == null) count = 10;
      var d2 = domain();
      var i0 = 0;
      var i1 = d2.length - 1;
      var start = d2[i0];
      var stop = d2[i1];
      var prestep;
      var step;
      var maxIter = 10;
      if (stop < start) {
        step = start, start = stop, stop = step;
        step = i0, i0 = i1, i1 = step;
      }
      while (maxIter-- > 0) {
        step = tickIncrement(start, stop, count);
        if (step === prestep) {
          d2[i0] = start;
          d2[i1] = stop;
          return domain(d2);
        } else if (step > 0) {
          start = Math.floor(start / step) * step;
          stop = Math.ceil(stop / step) * step;
        } else if (step < 0) {
          start = Math.ceil(start * step) / step;
          stop = Math.floor(stop * step) / step;
        } else {
          break;
        }
        prestep = step;
      }
      return scale;
    };
    return scale;
  }
  function linear2() {
    var scale = continuous();
    scale.copy = function() {
      return copy(scale, linear2());
    };
    initRange.apply(scale, arguments);
    return linearish(scale);
  }

  // node_modules/d3-scale/src/nice.js
  function nice(domain, interval) {
    domain = domain.slice();
    var i0 = 0, i1 = domain.length - 1, x0 = domain[i0], x1 = domain[i1], t;
    if (x1 < x0) {
      t = i0, i0 = i1, i1 = t;
      t = x0, x0 = x1, x1 = t;
    }
    domain[i0] = interval.floor(x0);
    domain[i1] = interval.ceil(x1);
    return domain;
  }

  // node_modules/d3-time/src/interval.js
  var t0 = /* @__PURE__ */ new Date();
  var t1 = /* @__PURE__ */ new Date();
  function timeInterval(floori, offseti, count, field) {
    function interval(date2) {
      return floori(date2 = arguments.length === 0 ? /* @__PURE__ */ new Date() : /* @__PURE__ */ new Date(+date2)), date2;
    }
    interval.floor = (date2) => {
      return floori(date2 = /* @__PURE__ */ new Date(+date2)), date2;
    };
    interval.ceil = (date2) => {
      return floori(date2 = new Date(date2 - 1)), offseti(date2, 1), floori(date2), date2;
    };
    interval.round = (date2) => {
      const d0 = interval(date2), d1 = interval.ceil(date2);
      return date2 - d0 < d1 - date2 ? d0 : d1;
    };
    interval.offset = (date2, step) => {
      return offseti(date2 = /* @__PURE__ */ new Date(+date2), step == null ? 1 : Math.floor(step)), date2;
    };
    interval.range = (start, stop, step) => {
      const range = [];
      start = interval.ceil(start);
      step = step == null ? 1 : Math.floor(step);
      if (!(start < stop) || !(step > 0)) return range;
      let previous;
      do
        range.push(previous = /* @__PURE__ */ new Date(+start)), offseti(start, step), floori(start);
      while (previous < start && start < stop);
      return range;
    };
    interval.filter = (test) => {
      return timeInterval((date2) => {
        if (date2 >= date2) while (floori(date2), !test(date2)) date2.setTime(date2 - 1);
      }, (date2, step) => {
        if (date2 >= date2) {
          if (step < 0) while (++step <= 0) {
            while (offseti(date2, -1), !test(date2)) {
            }
          }
          else while (--step >= 0) {
            while (offseti(date2, 1), !test(date2)) {
            }
          }
        }
      });
    };
    if (count) {
      interval.count = (start, end) => {
        t0.setTime(+start), t1.setTime(+end);
        floori(t0), floori(t1);
        return Math.floor(count(t0, t1));
      };
      interval.every = (step) => {
        step = Math.floor(step);
        return !isFinite(step) || !(step > 0) ? null : !(step > 1) ? interval : interval.filter(field ? (d2) => field(d2) % step === 0 : (d2) => interval.count(0, d2) % step === 0);
      };
    }
    return interval;
  }

  // node_modules/d3-time/src/millisecond.js
  var millisecond = timeInterval(() => {
  }, (date2, step) => {
    date2.setTime(+date2 + step);
  }, (start, end) => {
    return end - start;
  });
  millisecond.every = (k2) => {
    k2 = Math.floor(k2);
    if (!isFinite(k2) || !(k2 > 0)) return null;
    if (!(k2 > 1)) return millisecond;
    return timeInterval((date2) => {
      date2.setTime(Math.floor(date2 / k2) * k2);
    }, (date2, step) => {
      date2.setTime(+date2 + step * k2);
    }, (start, end) => {
      return (end - start) / k2;
    });
  };
  var milliseconds = millisecond.range;

  // node_modules/d3-time/src/duration.js
  var durationSecond = 1e3;
  var durationMinute = durationSecond * 60;
  var durationHour = durationMinute * 60;
  var durationDay = durationHour * 24;
  var durationWeek = durationDay * 7;
  var durationMonth = durationDay * 30;
  var durationYear = durationDay * 365;

  // node_modules/d3-time/src/second.js
  var second = timeInterval((date2) => {
    date2.setTime(date2 - date2.getMilliseconds());
  }, (date2, step) => {
    date2.setTime(+date2 + step * durationSecond);
  }, (start, end) => {
    return (end - start) / durationSecond;
  }, (date2) => {
    return date2.getUTCSeconds();
  });
  var seconds = second.range;

  // node_modules/d3-time/src/minute.js
  var timeMinute = timeInterval((date2) => {
    date2.setTime(date2 - date2.getMilliseconds() - date2.getSeconds() * durationSecond);
  }, (date2, step) => {
    date2.setTime(+date2 + step * durationMinute);
  }, (start, end) => {
    return (end - start) / durationMinute;
  }, (date2) => {
    return date2.getMinutes();
  });
  var timeMinutes = timeMinute.range;
  var utcMinute = timeInterval((date2) => {
    date2.setUTCSeconds(0, 0);
  }, (date2, step) => {
    date2.setTime(+date2 + step * durationMinute);
  }, (start, end) => {
    return (end - start) / durationMinute;
  }, (date2) => {
    return date2.getUTCMinutes();
  });
  var utcMinutes = utcMinute.range;

  // node_modules/d3-time/src/hour.js
  var timeHour = timeInterval((date2) => {
    date2.setTime(date2 - date2.getMilliseconds() - date2.getSeconds() * durationSecond - date2.getMinutes() * durationMinute);
  }, (date2, step) => {
    date2.setTime(+date2 + step * durationHour);
  }, (start, end) => {
    return (end - start) / durationHour;
  }, (date2) => {
    return date2.getHours();
  });
  var timeHours = timeHour.range;
  var utcHour = timeInterval((date2) => {
    date2.setUTCMinutes(0, 0, 0);
  }, (date2, step) => {
    date2.setTime(+date2 + step * durationHour);
  }, (start, end) => {
    return (end - start) / durationHour;
  }, (date2) => {
    return date2.getUTCHours();
  });
  var utcHours = utcHour.range;

  // node_modules/d3-time/src/day.js
  var timeDay = timeInterval(
    (date2) => date2.setHours(0, 0, 0, 0),
    (date2, step) => date2.setDate(date2.getDate() + step),
    (start, end) => (end - start - (end.getTimezoneOffset() - start.getTimezoneOffset()) * durationMinute) / durationDay,
    (date2) => date2.getDate() - 1
  );
  var timeDays = timeDay.range;
  var utcDay = timeInterval((date2) => {
    date2.setUTCHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setUTCDate(date2.getUTCDate() + step);
  }, (start, end) => {
    return (end - start) / durationDay;
  }, (date2) => {
    return date2.getUTCDate() - 1;
  });
  var utcDays = utcDay.range;
  var unixDay = timeInterval((date2) => {
    date2.setUTCHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setUTCDate(date2.getUTCDate() + step);
  }, (start, end) => {
    return (end - start) / durationDay;
  }, (date2) => {
    return Math.floor(date2 / durationDay);
  });
  var unixDays = unixDay.range;

  // node_modules/d3-time/src/week.js
  function timeWeekday(i) {
    return timeInterval((date2) => {
      date2.setDate(date2.getDate() - (date2.getDay() + 7 - i) % 7);
      date2.setHours(0, 0, 0, 0);
    }, (date2, step) => {
      date2.setDate(date2.getDate() + step * 7);
    }, (start, end) => {
      return (end - start - (end.getTimezoneOffset() - start.getTimezoneOffset()) * durationMinute) / durationWeek;
    });
  }
  var timeSunday = timeWeekday(0);
  var timeMonday = timeWeekday(1);
  var timeTuesday = timeWeekday(2);
  var timeWednesday = timeWeekday(3);
  var timeThursday = timeWeekday(4);
  var timeFriday = timeWeekday(5);
  var timeSaturday = timeWeekday(6);
  var timeSundays = timeSunday.range;
  var timeMondays = timeMonday.range;
  var timeTuesdays = timeTuesday.range;
  var timeWednesdays = timeWednesday.range;
  var timeThursdays = timeThursday.range;
  var timeFridays = timeFriday.range;
  var timeSaturdays = timeSaturday.range;
  function utcWeekday(i) {
    return timeInterval((date2) => {
      date2.setUTCDate(date2.getUTCDate() - (date2.getUTCDay() + 7 - i) % 7);
      date2.setUTCHours(0, 0, 0, 0);
    }, (date2, step) => {
      date2.setUTCDate(date2.getUTCDate() + step * 7);
    }, (start, end) => {
      return (end - start) / durationWeek;
    });
  }
  var utcSunday = utcWeekday(0);
  var utcMonday = utcWeekday(1);
  var utcTuesday = utcWeekday(2);
  var utcWednesday = utcWeekday(3);
  var utcThursday = utcWeekday(4);
  var utcFriday = utcWeekday(5);
  var utcSaturday = utcWeekday(6);
  var utcSundays = utcSunday.range;
  var utcMondays = utcMonday.range;
  var utcTuesdays = utcTuesday.range;
  var utcWednesdays = utcWednesday.range;
  var utcThursdays = utcThursday.range;
  var utcFridays = utcFriday.range;
  var utcSaturdays = utcSaturday.range;

  // node_modules/d3-time/src/month.js
  var timeMonth = timeInterval((date2) => {
    date2.setDate(1);
    date2.setHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setMonth(date2.getMonth() + step);
  }, (start, end) => {
    return end.getMonth() - start.getMonth() + (end.getFullYear() - start.getFullYear()) * 12;
  }, (date2) => {
    return date2.getMonth();
  });
  var timeMonths = timeMonth.range;
  var utcMonth = timeInterval((date2) => {
    date2.setUTCDate(1);
    date2.setUTCHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setUTCMonth(date2.getUTCMonth() + step);
  }, (start, end) => {
    return end.getUTCMonth() - start.getUTCMonth() + (end.getUTCFullYear() - start.getUTCFullYear()) * 12;
  }, (date2) => {
    return date2.getUTCMonth();
  });
  var utcMonths = utcMonth.range;

  // node_modules/d3-time/src/year.js
  var timeYear = timeInterval((date2) => {
    date2.setMonth(0, 1);
    date2.setHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setFullYear(date2.getFullYear() + step);
  }, (start, end) => {
    return end.getFullYear() - start.getFullYear();
  }, (date2) => {
    return date2.getFullYear();
  });
  timeYear.every = (k2) => {
    return !isFinite(k2 = Math.floor(k2)) || !(k2 > 0) ? null : timeInterval((date2) => {
      date2.setFullYear(Math.floor(date2.getFullYear() / k2) * k2);
      date2.setMonth(0, 1);
      date2.setHours(0, 0, 0, 0);
    }, (date2, step) => {
      date2.setFullYear(date2.getFullYear() + step * k2);
    });
  };
  var timeYears = timeYear.range;
  var utcYear = timeInterval((date2) => {
    date2.setUTCMonth(0, 1);
    date2.setUTCHours(0, 0, 0, 0);
  }, (date2, step) => {
    date2.setUTCFullYear(date2.getUTCFullYear() + step);
  }, (start, end) => {
    return end.getUTCFullYear() - start.getUTCFullYear();
  }, (date2) => {
    return date2.getUTCFullYear();
  });
  utcYear.every = (k2) => {
    return !isFinite(k2 = Math.floor(k2)) || !(k2 > 0) ? null : timeInterval((date2) => {
      date2.setUTCFullYear(Math.floor(date2.getUTCFullYear() / k2) * k2);
      date2.setUTCMonth(0, 1);
      date2.setUTCHours(0, 0, 0, 0);
    }, (date2, step) => {
      date2.setUTCFullYear(date2.getUTCFullYear() + step * k2);
    });
  };
  var utcYears = utcYear.range;

  // node_modules/d3-time/src/ticks.js
  function ticker(year, month, week, day, hour, minute) {
    const tickIntervals = [
      [second, 1, durationSecond],
      [second, 5, 5 * durationSecond],
      [second, 15, 15 * durationSecond],
      [second, 30, 30 * durationSecond],
      [minute, 1, durationMinute],
      [minute, 5, 5 * durationMinute],
      [minute, 15, 15 * durationMinute],
      [minute, 30, 30 * durationMinute],
      [hour, 1, durationHour],
      [hour, 3, 3 * durationHour],
      [hour, 6, 6 * durationHour],
      [hour, 12, 12 * durationHour],
      [day, 1, durationDay],
      [day, 2, 2 * durationDay],
      [week, 1, durationWeek],
      [month, 1, durationMonth],
      [month, 3, 3 * durationMonth],
      [year, 1, durationYear]
    ];
    function ticks2(start, stop, count) {
      const reverse = stop < start;
      if (reverse) [start, stop] = [stop, start];
      const interval = count && typeof count.range === "function" ? count : tickInterval(start, stop, count);
      const ticks3 = interval ? interval.range(start, +stop + 1) : [];
      return reverse ? ticks3.reverse() : ticks3;
    }
    function tickInterval(start, stop, count) {
      const target = Math.abs(stop - start) / count;
      const i = bisector(([, , step2]) => step2).right(tickIntervals, target);
      if (i === tickIntervals.length) return year.every(tickStep(start / durationYear, stop / durationYear, count));
      if (i === 0) return millisecond.every(Math.max(tickStep(start, stop, count), 1));
      const [t, step] = tickIntervals[target / tickIntervals[i - 1][2] < tickIntervals[i][2] / target ? i - 1 : i];
      return t.every(step);
    }
    return [ticks2, tickInterval];
  }
  var [utcTicks, utcTickInterval] = ticker(utcYear, utcMonth, utcSunday, unixDay, utcHour, utcMinute);
  var [timeTicks, timeTickInterval] = ticker(timeYear, timeMonth, timeSunday, timeDay, timeHour, timeMinute);

  // node_modules/d3-time-format/src/locale.js
  function localDate(d2) {
    if (0 <= d2.y && d2.y < 100) {
      var date2 = new Date(-1, d2.m, d2.d, d2.H, d2.M, d2.S, d2.L);
      date2.setFullYear(d2.y);
      return date2;
    }
    return new Date(d2.y, d2.m, d2.d, d2.H, d2.M, d2.S, d2.L);
  }
  function utcDate(d2) {
    if (0 <= d2.y && d2.y < 100) {
      var date2 = new Date(Date.UTC(-1, d2.m, d2.d, d2.H, d2.M, d2.S, d2.L));
      date2.setUTCFullYear(d2.y);
      return date2;
    }
    return new Date(Date.UTC(d2.y, d2.m, d2.d, d2.H, d2.M, d2.S, d2.L));
  }
  function newDate(y3, m2, d2) {
    return { y: y3, m: m2, d: d2, H: 0, M: 0, S: 0, L: 0 };
  }
  function formatLocale(locale3) {
    var locale_dateTime = locale3.dateTime, locale_date = locale3.date, locale_time = locale3.time, locale_periods = locale3.periods, locale_weekdays = locale3.days, locale_shortWeekdays = locale3.shortDays, locale_months = locale3.months, locale_shortMonths = locale3.shortMonths;
    var periodRe = formatRe(locale_periods), periodLookup = formatLookup(locale_periods), weekdayRe = formatRe(locale_weekdays), weekdayLookup = formatLookup(locale_weekdays), shortWeekdayRe = formatRe(locale_shortWeekdays), shortWeekdayLookup = formatLookup(locale_shortWeekdays), monthRe = formatRe(locale_months), monthLookup = formatLookup(locale_months), shortMonthRe = formatRe(locale_shortMonths), shortMonthLookup = formatLookup(locale_shortMonths);
    var formats = {
      "a": formatShortWeekday,
      "A": formatWeekday,
      "b": formatShortMonth,
      "B": formatMonth,
      "c": null,
      "d": formatDayOfMonth,
      "e": formatDayOfMonth,
      "f": formatMicroseconds,
      "g": formatYearISO,
      "G": formatFullYearISO,
      "H": formatHour24,
      "I": formatHour12,
      "j": formatDayOfYear,
      "L": formatMilliseconds,
      "m": formatMonthNumber,
      "M": formatMinutes,
      "p": formatPeriod,
      "q": formatQuarter,
      "Q": formatUnixTimestamp,
      "s": formatUnixTimestampSeconds,
      "S": formatSeconds,
      "u": formatWeekdayNumberMonday,
      "U": formatWeekNumberSunday,
      "V": formatWeekNumberISO,
      "w": formatWeekdayNumberSunday,
      "W": formatWeekNumberMonday,
      "x": null,
      "X": null,
      "y": formatYear,
      "Y": formatFullYear,
      "Z": formatZone,
      "%": formatLiteralPercent
    };
    var utcFormats = {
      "a": formatUTCShortWeekday,
      "A": formatUTCWeekday,
      "b": formatUTCShortMonth,
      "B": formatUTCMonth,
      "c": null,
      "d": formatUTCDayOfMonth,
      "e": formatUTCDayOfMonth,
      "f": formatUTCMicroseconds,
      "g": formatUTCYearISO,
      "G": formatUTCFullYearISO,
      "H": formatUTCHour24,
      "I": formatUTCHour12,
      "j": formatUTCDayOfYear,
      "L": formatUTCMilliseconds,
      "m": formatUTCMonthNumber,
      "M": formatUTCMinutes,
      "p": formatUTCPeriod,
      "q": formatUTCQuarter,
      "Q": formatUnixTimestamp,
      "s": formatUnixTimestampSeconds,
      "S": formatUTCSeconds,
      "u": formatUTCWeekdayNumberMonday,
      "U": formatUTCWeekNumberSunday,
      "V": formatUTCWeekNumberISO,
      "w": formatUTCWeekdayNumberSunday,
      "W": formatUTCWeekNumberMonday,
      "x": null,
      "X": null,
      "y": formatUTCYear,
      "Y": formatUTCFullYear,
      "Z": formatUTCZone,
      "%": formatLiteralPercent
    };
    var parses = {
      "a": parseShortWeekday,
      "A": parseWeekday,
      "b": parseShortMonth,
      "B": parseMonth,
      "c": parseLocaleDateTime,
      "d": parseDayOfMonth,
      "e": parseDayOfMonth,
      "f": parseMicroseconds,
      "g": parseYear,
      "G": parseFullYear,
      "H": parseHour24,
      "I": parseHour24,
      "j": parseDayOfYear,
      "L": parseMilliseconds,
      "m": parseMonthNumber,
      "M": parseMinutes,
      "p": parsePeriod,
      "q": parseQuarter,
      "Q": parseUnixTimestamp,
      "s": parseUnixTimestampSeconds,
      "S": parseSeconds,
      "u": parseWeekdayNumberMonday,
      "U": parseWeekNumberSunday,
      "V": parseWeekNumberISO,
      "w": parseWeekdayNumberSunday,
      "W": parseWeekNumberMonday,
      "x": parseLocaleDate,
      "X": parseLocaleTime,
      "y": parseYear,
      "Y": parseFullYear,
      "Z": parseZone,
      "%": parseLiteralPercent
    };
    formats.x = newFormat(locale_date, formats);
    formats.X = newFormat(locale_time, formats);
    formats.c = newFormat(locale_dateTime, formats);
    utcFormats.x = newFormat(locale_date, utcFormats);
    utcFormats.X = newFormat(locale_time, utcFormats);
    utcFormats.c = newFormat(locale_dateTime, utcFormats);
    function newFormat(specifier, formats2) {
      return function(date2) {
        var string = [], i = -1, j2 = 0, n = specifier.length, c2, pad2, format2;
        if (!(date2 instanceof Date)) date2 = /* @__PURE__ */ new Date(+date2);
        while (++i < n) {
          if (specifier.charCodeAt(i) === 37) {
            string.push(specifier.slice(j2, i));
            if ((pad2 = pads[c2 = specifier.charAt(++i)]) != null) c2 = specifier.charAt(++i);
            else pad2 = c2 === "e" ? " " : "0";
            if (format2 = formats2[c2]) c2 = format2(date2, pad2);
            string.push(c2);
            j2 = i + 1;
          }
        }
        string.push(specifier.slice(j2, i));
        return string.join("");
      };
    }
    function newParse(specifier, Z2) {
      return function(string) {
        var d2 = newDate(1900, void 0, 1), i = parseSpecifier(d2, specifier, string += "", 0), week, day;
        if (i != string.length) return null;
        if ("Q" in d2) return new Date(d2.Q);
        if ("s" in d2) return new Date(d2.s * 1e3 + ("L" in d2 ? d2.L : 0));
        if (Z2 && !("Z" in d2)) d2.Z = 0;
        if ("p" in d2) d2.H = d2.H % 12 + d2.p * 12;
        if (d2.m === void 0) d2.m = "q" in d2 ? d2.q : 0;
        if ("V" in d2) {
          if (d2.V < 1 || d2.V > 53) return null;
          if (!("w" in d2)) d2.w = 1;
          if ("Z" in d2) {
            week = utcDate(newDate(d2.y, 0, 1)), day = week.getUTCDay();
            week = day > 4 || day === 0 ? utcMonday.ceil(week) : utcMonday(week);
            week = utcDay.offset(week, (d2.V - 1) * 7);
            d2.y = week.getUTCFullYear();
            d2.m = week.getUTCMonth();
            d2.d = week.getUTCDate() + (d2.w + 6) % 7;
          } else {
            week = localDate(newDate(d2.y, 0, 1)), day = week.getDay();
            week = day > 4 || day === 0 ? timeMonday.ceil(week) : timeMonday(week);
            week = timeDay.offset(week, (d2.V - 1) * 7);
            d2.y = week.getFullYear();
            d2.m = week.getMonth();
            d2.d = week.getDate() + (d2.w + 6) % 7;
          }
        } else if ("W" in d2 || "U" in d2) {
          if (!("w" in d2)) d2.w = "u" in d2 ? d2.u % 7 : "W" in d2 ? 1 : 0;
          day = "Z" in d2 ? utcDate(newDate(d2.y, 0, 1)).getUTCDay() : localDate(newDate(d2.y, 0, 1)).getDay();
          d2.m = 0;
          d2.d = "W" in d2 ? (d2.w + 6) % 7 + d2.W * 7 - (day + 5) % 7 : d2.w + d2.U * 7 - (day + 6) % 7;
        }
        if ("Z" in d2) {
          d2.H += d2.Z / 100 | 0;
          d2.M += d2.Z % 100;
          return utcDate(d2);
        }
        return localDate(d2);
      };
    }
    function parseSpecifier(d2, specifier, string, j2) {
      var i = 0, n = specifier.length, m2 = string.length, c2, parse;
      while (i < n) {
        if (j2 >= m2) return -1;
        c2 = specifier.charCodeAt(i++);
        if (c2 === 37) {
          c2 = specifier.charAt(i++);
          parse = parses[c2 in pads ? specifier.charAt(i++) : c2];
          if (!parse || (j2 = parse(d2, string, j2)) < 0) return -1;
        } else if (c2 != string.charCodeAt(j2++)) {
          return -1;
        }
      }
      return j2;
    }
    function parsePeriod(d2, string, i) {
      var n = periodRe.exec(string.slice(i));
      return n ? (d2.p = periodLookup.get(n[0].toLowerCase()), i + n[0].length) : -1;
    }
    function parseShortWeekday(d2, string, i) {
      var n = shortWeekdayRe.exec(string.slice(i));
      return n ? (d2.w = shortWeekdayLookup.get(n[0].toLowerCase()), i + n[0].length) : -1;
    }
    function parseWeekday(d2, string, i) {
      var n = weekdayRe.exec(string.slice(i));
      return n ? (d2.w = weekdayLookup.get(n[0].toLowerCase()), i + n[0].length) : -1;
    }
    function parseShortMonth(d2, string, i) {
      var n = shortMonthRe.exec(string.slice(i));
      return n ? (d2.m = shortMonthLookup.get(n[0].toLowerCase()), i + n[0].length) : -1;
    }
    function parseMonth(d2, string, i) {
      var n = monthRe.exec(string.slice(i));
      return n ? (d2.m = monthLookup.get(n[0].toLowerCase()), i + n[0].length) : -1;
    }
    function parseLocaleDateTime(d2, string, i) {
      return parseSpecifier(d2, locale_dateTime, string, i);
    }
    function parseLocaleDate(d2, string, i) {
      return parseSpecifier(d2, locale_date, string, i);
    }
    function parseLocaleTime(d2, string, i) {
      return parseSpecifier(d2, locale_time, string, i);
    }
    function formatShortWeekday(d2) {
      return locale_shortWeekdays[d2.getDay()];
    }
    function formatWeekday(d2) {
      return locale_weekdays[d2.getDay()];
    }
    function formatShortMonth(d2) {
      return locale_shortMonths[d2.getMonth()];
    }
    function formatMonth(d2) {
      return locale_months[d2.getMonth()];
    }
    function formatPeriod(d2) {
      return locale_periods[+(d2.getHours() >= 12)];
    }
    function formatQuarter(d2) {
      return 1 + ~~(d2.getMonth() / 3);
    }
    function formatUTCShortWeekday(d2) {
      return locale_shortWeekdays[d2.getUTCDay()];
    }
    function formatUTCWeekday(d2) {
      return locale_weekdays[d2.getUTCDay()];
    }
    function formatUTCShortMonth(d2) {
      return locale_shortMonths[d2.getUTCMonth()];
    }
    function formatUTCMonth(d2) {
      return locale_months[d2.getUTCMonth()];
    }
    function formatUTCPeriod(d2) {
      return locale_periods[+(d2.getUTCHours() >= 12)];
    }
    function formatUTCQuarter(d2) {
      return 1 + ~~(d2.getUTCMonth() / 3);
    }
    return {
      format: function(specifier) {
        var f2 = newFormat(specifier += "", formats);
        f2.toString = function() {
          return specifier;
        };
        return f2;
      },
      parse: function(specifier) {
        var p2 = newParse(specifier += "", false);
        p2.toString = function() {
          return specifier;
        };
        return p2;
      },
      utcFormat: function(specifier) {
        var f2 = newFormat(specifier += "", utcFormats);
        f2.toString = function() {
          return specifier;
        };
        return f2;
      },
      utcParse: function(specifier) {
        var p2 = newParse(specifier += "", true);
        p2.toString = function() {
          return specifier;
        };
        return p2;
      }
    };
  }
  var pads = { "-": "", "_": " ", "0": "0" };
  var numberRe = /^\s*\d+/;
  var percentRe = /^%/;
  var requoteRe = /[\\^$*+?|[\]().{}]/g;
  function pad(value, fill, width) {
    var sign = value < 0 ? "-" : "", string = (sign ? -value : value) + "", length = string.length;
    return sign + (length < width ? new Array(width - length + 1).join(fill) + string : string);
  }
  function requote(s) {
    return s.replace(requoteRe, "\\$&");
  }
  function formatRe(names) {
    return new RegExp("^(?:" + names.map(requote).join("|") + ")", "i");
  }
  function formatLookup(names) {
    return new Map(names.map((name, i) => [name.toLowerCase(), i]));
  }
  function parseWeekdayNumberSunday(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 1));
    return n ? (d2.w = +n[0], i + n[0].length) : -1;
  }
  function parseWeekdayNumberMonday(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 1));
    return n ? (d2.u = +n[0], i + n[0].length) : -1;
  }
  function parseWeekNumberSunday(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.U = +n[0], i + n[0].length) : -1;
  }
  function parseWeekNumberISO(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.V = +n[0], i + n[0].length) : -1;
  }
  function parseWeekNumberMonday(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.W = +n[0], i + n[0].length) : -1;
  }
  function parseFullYear(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 4));
    return n ? (d2.y = +n[0], i + n[0].length) : -1;
  }
  function parseYear(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.y = +n[0] + (+n[0] > 68 ? 1900 : 2e3), i + n[0].length) : -1;
  }
  function parseZone(d2, string, i) {
    var n = /^(Z)|([+-]\d\d)(?::?(\d\d))?/.exec(string.slice(i, i + 6));
    return n ? (d2.Z = n[1] ? 0 : -(n[2] + (n[3] || "00")), i + n[0].length) : -1;
  }
  function parseQuarter(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 1));
    return n ? (d2.q = n[0] * 3 - 3, i + n[0].length) : -1;
  }
  function parseMonthNumber(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.m = n[0] - 1, i + n[0].length) : -1;
  }
  function parseDayOfMonth(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.d = +n[0], i + n[0].length) : -1;
  }
  function parseDayOfYear(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 3));
    return n ? (d2.m = 0, d2.d = +n[0], i + n[0].length) : -1;
  }
  function parseHour24(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.H = +n[0], i + n[0].length) : -1;
  }
  function parseMinutes(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.M = +n[0], i + n[0].length) : -1;
  }
  function parseSeconds(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 2));
    return n ? (d2.S = +n[0], i + n[0].length) : -1;
  }
  function parseMilliseconds(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 3));
    return n ? (d2.L = +n[0], i + n[0].length) : -1;
  }
  function parseMicroseconds(d2, string, i) {
    var n = numberRe.exec(string.slice(i, i + 6));
    return n ? (d2.L = Math.floor(n[0] / 1e3), i + n[0].length) : -1;
  }
  function parseLiteralPercent(d2, string, i) {
    var n = percentRe.exec(string.slice(i, i + 1));
    return n ? i + n[0].length : -1;
  }
  function parseUnixTimestamp(d2, string, i) {
    var n = numberRe.exec(string.slice(i));
    return n ? (d2.Q = +n[0], i + n[0].length) : -1;
  }
  function parseUnixTimestampSeconds(d2, string, i) {
    var n = numberRe.exec(string.slice(i));
    return n ? (d2.s = +n[0], i + n[0].length) : -1;
  }
  function formatDayOfMonth(d2, p2) {
    return pad(d2.getDate(), p2, 2);
  }
  function formatHour24(d2, p2) {
    return pad(d2.getHours(), p2, 2);
  }
  function formatHour12(d2, p2) {
    return pad(d2.getHours() % 12 || 12, p2, 2);
  }
  function formatDayOfYear(d2, p2) {
    return pad(1 + timeDay.count(timeYear(d2), d2), p2, 3);
  }
  function formatMilliseconds(d2, p2) {
    return pad(d2.getMilliseconds(), p2, 3);
  }
  function formatMicroseconds(d2, p2) {
    return formatMilliseconds(d2, p2) + "000";
  }
  function formatMonthNumber(d2, p2) {
    return pad(d2.getMonth() + 1, p2, 2);
  }
  function formatMinutes(d2, p2) {
    return pad(d2.getMinutes(), p2, 2);
  }
  function formatSeconds(d2, p2) {
    return pad(d2.getSeconds(), p2, 2);
  }
  function formatWeekdayNumberMonday(d2) {
    var day = d2.getDay();
    return day === 0 ? 7 : day;
  }
  function formatWeekNumberSunday(d2, p2) {
    return pad(timeSunday.count(timeYear(d2) - 1, d2), p2, 2);
  }
  function dISO(d2) {
    var day = d2.getDay();
    return day >= 4 || day === 0 ? timeThursday(d2) : timeThursday.ceil(d2);
  }
  function formatWeekNumberISO(d2, p2) {
    d2 = dISO(d2);
    return pad(timeThursday.count(timeYear(d2), d2) + (timeYear(d2).getDay() === 4), p2, 2);
  }
  function formatWeekdayNumberSunday(d2) {
    return d2.getDay();
  }
  function formatWeekNumberMonday(d2, p2) {
    return pad(timeMonday.count(timeYear(d2) - 1, d2), p2, 2);
  }
  function formatYear(d2, p2) {
    return pad(d2.getFullYear() % 100, p2, 2);
  }
  function formatYearISO(d2, p2) {
    d2 = dISO(d2);
    return pad(d2.getFullYear() % 100, p2, 2);
  }
  function formatFullYear(d2, p2) {
    return pad(d2.getFullYear() % 1e4, p2, 4);
  }
  function formatFullYearISO(d2, p2) {
    var day = d2.getDay();
    d2 = day >= 4 || day === 0 ? timeThursday(d2) : timeThursday.ceil(d2);
    return pad(d2.getFullYear() % 1e4, p2, 4);
  }
  function formatZone(d2) {
    var z2 = d2.getTimezoneOffset();
    return (z2 > 0 ? "-" : (z2 *= -1, "+")) + pad(z2 / 60 | 0, "0", 2) + pad(z2 % 60, "0", 2);
  }
  function formatUTCDayOfMonth(d2, p2) {
    return pad(d2.getUTCDate(), p2, 2);
  }
  function formatUTCHour24(d2, p2) {
    return pad(d2.getUTCHours(), p2, 2);
  }
  function formatUTCHour12(d2, p2) {
    return pad(d2.getUTCHours() % 12 || 12, p2, 2);
  }
  function formatUTCDayOfYear(d2, p2) {
    return pad(1 + utcDay.count(utcYear(d2), d2), p2, 3);
  }
  function formatUTCMilliseconds(d2, p2) {
    return pad(d2.getUTCMilliseconds(), p2, 3);
  }
  function formatUTCMicroseconds(d2, p2) {
    return formatUTCMilliseconds(d2, p2) + "000";
  }
  function formatUTCMonthNumber(d2, p2) {
    return pad(d2.getUTCMonth() + 1, p2, 2);
  }
  function formatUTCMinutes(d2, p2) {
    return pad(d2.getUTCMinutes(), p2, 2);
  }
  function formatUTCSeconds(d2, p2) {
    return pad(d2.getUTCSeconds(), p2, 2);
  }
  function formatUTCWeekdayNumberMonday(d2) {
    var dow = d2.getUTCDay();
    return dow === 0 ? 7 : dow;
  }
  function formatUTCWeekNumberSunday(d2, p2) {
    return pad(utcSunday.count(utcYear(d2) - 1, d2), p2, 2);
  }
  function UTCdISO(d2) {
    var day = d2.getUTCDay();
    return day >= 4 || day === 0 ? utcThursday(d2) : utcThursday.ceil(d2);
  }
  function formatUTCWeekNumberISO(d2, p2) {
    d2 = UTCdISO(d2);
    return pad(utcThursday.count(utcYear(d2), d2) + (utcYear(d2).getUTCDay() === 4), p2, 2);
  }
  function formatUTCWeekdayNumberSunday(d2) {
    return d2.getUTCDay();
  }
  function formatUTCWeekNumberMonday(d2, p2) {
    return pad(utcMonday.count(utcYear(d2) - 1, d2), p2, 2);
  }
  function formatUTCYear(d2, p2) {
    return pad(d2.getUTCFullYear() % 100, p2, 2);
  }
  function formatUTCYearISO(d2, p2) {
    d2 = UTCdISO(d2);
    return pad(d2.getUTCFullYear() % 100, p2, 2);
  }
  function formatUTCFullYear(d2, p2) {
    return pad(d2.getUTCFullYear() % 1e4, p2, 4);
  }
  function formatUTCFullYearISO(d2, p2) {
    var day = d2.getUTCDay();
    d2 = day >= 4 || day === 0 ? utcThursday(d2) : utcThursday.ceil(d2);
    return pad(d2.getUTCFullYear() % 1e4, p2, 4);
  }
  function formatUTCZone() {
    return "+0000";
  }
  function formatLiteralPercent() {
    return "%";
  }
  function formatUnixTimestamp(d2) {
    return +d2;
  }
  function formatUnixTimestampSeconds(d2) {
    return Math.floor(+d2 / 1e3);
  }

  // node_modules/d3-time-format/src/defaultLocale.js
  var locale2;
  var timeFormat;
  var timeParse;
  var utcFormat;
  var utcParse;
  defaultLocale2({
    dateTime: "%x, %X",
    date: "%-m/%-d/%Y",
    time: "%-I:%M:%S %p",
    periods: ["AM", "PM"],
    days: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
    shortDays: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    months: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    shortMonths: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  });
  function defaultLocale2(definition) {
    locale2 = formatLocale(definition);
    timeFormat = locale2.format;
    timeParse = locale2.parse;
    utcFormat = locale2.utcFormat;
    utcParse = locale2.utcParse;
    return locale2;
  }

  // node_modules/d3-scale/src/time.js
  function date(t) {
    return new Date(t);
  }
  function number3(t) {
    return t instanceof Date ? +t : +/* @__PURE__ */ new Date(+t);
  }
  function calendar(ticks2, tickInterval, year, month, week, day, hour, minute, second2, format2) {
    var scale = continuous(), invert = scale.invert, domain = scale.domain;
    var formatMillisecond = format2(".%L"), formatSecond = format2(":%S"), formatMinute = format2("%I:%M"), formatHour = format2("%I %p"), formatDay = format2("%a %d"), formatWeek = format2("%b %d"), formatMonth = format2("%B"), formatYear2 = format2("%Y");
    function tickFormat2(date2) {
      return (second2(date2) < date2 ? formatMillisecond : minute(date2) < date2 ? formatSecond : hour(date2) < date2 ? formatMinute : day(date2) < date2 ? formatHour : month(date2) < date2 ? week(date2) < date2 ? formatDay : formatWeek : year(date2) < date2 ? formatMonth : formatYear2)(date2);
    }
    scale.invert = function(y3) {
      return new Date(invert(y3));
    };
    scale.domain = function(_2) {
      return arguments.length ? domain(Array.from(_2, number3)) : domain().map(date);
    };
    scale.ticks = function(interval) {
      var d2 = domain();
      return ticks2(d2[0], d2[d2.length - 1], interval == null ? 10 : interval);
    };
    scale.tickFormat = function(count, specifier) {
      return specifier == null ? tickFormat2 : format2(specifier);
    };
    scale.nice = function(interval) {
      var d2 = domain();
      if (!interval || typeof interval.range !== "function") interval = tickInterval(d2[0], d2[d2.length - 1], interval == null ? 10 : interval);
      return interval ? domain(nice(d2, interval)) : scale;
    };
    scale.copy = function() {
      return copy(scale, calendar(ticks2, tickInterval, year, month, week, day, hour, minute, second2, format2));
    };
    return scale;
  }
  function time() {
    return initRange.apply(calendar(timeTicks, timeTickInterval, timeYear, timeMonth, timeSunday, timeDay, timeHour, timeMinute, second, timeFormat).domain([new Date(2e3, 0, 1), new Date(2e3, 0, 2)]), arguments);
  }

  // node_modules/d3-shape/src/constant.js
  function constant_default2(x3) {
    return function constant() {
      return x3;
    };
  }

  // node_modules/d3-path/src/path.js
  var pi2 = Math.PI;
  var tau = 2 * pi2;
  var epsilon = 1e-6;
  var tauEpsilon = tau - epsilon;
  function append(strings) {
    this._ += strings[0];
    for (let i = 1, n = strings.length; i < n; ++i) {
      this._ += arguments[i] + strings[i];
    }
  }
  function appendRound(digits) {
    let d2 = Math.floor(digits);
    if (!(d2 >= 0)) throw new Error(`invalid digits: ${digits}`);
    if (d2 > 15) return append;
    const k2 = 10 ** d2;
    return function(strings) {
      this._ += strings[0];
      for (let i = 1, n = strings.length; i < n; ++i) {
        this._ += Math.round(arguments[i] * k2) / k2 + strings[i];
      }
    };
  }
  var Path = class {
    constructor(digits) {
      this._x0 = this._y0 = // start of current subpath
      this._x1 = this._y1 = null;
      this._ = "";
      this._append = digits == null ? append : appendRound(digits);
    }
    moveTo(x3, y3) {
      this._append`M${this._x0 = this._x1 = +x3},${this._y0 = this._y1 = +y3}`;
    }
    closePath() {
      if (this._x1 !== null) {
        this._x1 = this._x0, this._y1 = this._y0;
        this._append`Z`;
      }
    }
    lineTo(x3, y3) {
      this._append`L${this._x1 = +x3},${this._y1 = +y3}`;
    }
    quadraticCurveTo(x1, y1, x3, y3) {
      this._append`Q${+x1},${+y1},${this._x1 = +x3},${this._y1 = +y3}`;
    }
    bezierCurveTo(x1, y1, x22, y22, x3, y3) {
      this._append`C${+x1},${+y1},${+x22},${+y22},${this._x1 = +x3},${this._y1 = +y3}`;
    }
    arcTo(x1, y1, x22, y22, r2) {
      x1 = +x1, y1 = +y1, x22 = +x22, y22 = +y22, r2 = +r2;
      if (r2 < 0) throw new Error(`negative radius: ${r2}`);
      let x0 = this._x1, y0 = this._y1, x21 = x22 - x1, y21 = y22 - y1, x01 = x0 - x1, y01 = y0 - y1, l01_2 = x01 * x01 + y01 * y01;
      if (this._x1 === null) {
        this._append`M${this._x1 = x1},${this._y1 = y1}`;
      } else if (!(l01_2 > epsilon)) ;
      else if (!(Math.abs(y01 * x21 - y21 * x01) > epsilon) || !r2) {
        this._append`L${this._x1 = x1},${this._y1 = y1}`;
      } else {
        let x20 = x22 - x0, y20 = y22 - y0, l21_2 = x21 * x21 + y21 * y21, l20_2 = x20 * x20 + y20 * y20, l21 = Math.sqrt(l21_2), l01 = Math.sqrt(l01_2), l2 = r2 * Math.tan((pi2 - Math.acos((l21_2 + l01_2 - l20_2) / (2 * l21 * l01))) / 2), t01 = l2 / l01, t21 = l2 / l21;
        if (Math.abs(t01 - 1) > epsilon) {
          this._append`L${x1 + t01 * x01},${y1 + t01 * y01}`;
        }
        this._append`A${r2},${r2},0,0,${+(y01 * x20 > x01 * y20)},${this._x1 = x1 + t21 * x21},${this._y1 = y1 + t21 * y21}`;
      }
    }
    arc(x3, y3, r2, a0, a1, ccw) {
      x3 = +x3, y3 = +y3, r2 = +r2, ccw = !!ccw;
      if (r2 < 0) throw new Error(`negative radius: ${r2}`);
      let dx = r2 * Math.cos(a0), dy = r2 * Math.sin(a0), x0 = x3 + dx, y0 = y3 + dy, cw = 1 ^ ccw, da = ccw ? a0 - a1 : a1 - a0;
      if (this._x1 === null) {
        this._append`M${x0},${y0}`;
      } else if (Math.abs(this._x1 - x0) > epsilon || Math.abs(this._y1 - y0) > epsilon) {
        this._append`L${x0},${y0}`;
      }
      if (!r2) return;
      if (da < 0) da = da % tau + tau;
      if (da > tauEpsilon) {
        this._append`A${r2},${r2},0,1,${cw},${x3 - dx},${y3 - dy}A${r2},${r2},0,1,${cw},${this._x1 = x0},${this._y1 = y0}`;
      } else if (da > epsilon) {
        this._append`A${r2},${r2},0,${+(da >= pi2)},${cw},${this._x1 = x3 + r2 * Math.cos(a1)},${this._y1 = y3 + r2 * Math.sin(a1)}`;
      }
    }
    rect(x3, y3, w2, h2) {
      this._append`M${this._x0 = this._x1 = +x3},${this._y0 = this._y1 = +y3}h${w2 = +w2}v${+h2}h${-w2}Z`;
    }
    toString() {
      return this._;
    }
  };
  function path() {
    return new Path();
  }
  path.prototype = Path.prototype;

  // node_modules/d3-shape/src/path.js
  function withPath(shape) {
    let digits = 3;
    shape.digits = function(_2) {
      if (!arguments.length) return digits;
      if (_2 == null) {
        digits = null;
      } else {
        const d2 = Math.floor(_2);
        if (!(d2 >= 0)) throw new RangeError(`invalid digits: ${_2}`);
        digits = d2;
      }
      return shape;
    };
    return () => new Path(digits);
  }

  // node_modules/d3-shape/src/array.js
  var slice = Array.prototype.slice;
  function array_default(x3) {
    return typeof x3 === "object" && "length" in x3 ? x3 : Array.from(x3);
  }

  // node_modules/d3-shape/src/curve/linear.js
  function Linear(context) {
    this._context = context;
  }
  Linear.prototype = {
    areaStart: function() {
      this._line = 0;
    },
    areaEnd: function() {
      this._line = NaN;
    },
    lineStart: function() {
      this._point = 0;
    },
    lineEnd: function() {
      if (this._line || this._line !== 0 && this._point === 1) this._context.closePath();
      this._line = 1 - this._line;
    },
    point: function(x3, y3) {
      x3 = +x3, y3 = +y3;
      switch (this._point) {
        case 0:
          this._point = 1;
          this._line ? this._context.lineTo(x3, y3) : this._context.moveTo(x3, y3);
          break;
        case 1:
          this._point = 2;
        // falls through
        default:
          this._context.lineTo(x3, y3);
          break;
      }
    }
  };
  function linear_default(context) {
    return new Linear(context);
  }

  // node_modules/d3-shape/src/point.js
  function x2(p2) {
    return p2[0];
  }
  function y2(p2) {
    return p2[1];
  }

  // node_modules/d3-shape/src/line.js
  function line_default(x3, y3) {
    var defined = constant_default2(true), context = null, curve = linear_default, output = null, path2 = withPath(line);
    x3 = typeof x3 === "function" ? x3 : x3 === void 0 ? x2 : constant_default2(x3);
    y3 = typeof y3 === "function" ? y3 : y3 === void 0 ? y2 : constant_default2(y3);
    function line(data) {
      var i, n = (data = array_default(data)).length, d2, defined0 = false, buffer;
      if (context == null) output = curve(buffer = path2());
      for (i = 0; i <= n; ++i) {
        if (!(i < n && defined(d2 = data[i], i, data)) === defined0) {
          if (defined0 = !defined0) output.lineStart();
          else output.lineEnd();
        }
        if (defined0) output.point(+x3(d2, i, data), +y3(d2, i, data));
      }
      if (buffer) return output = null, buffer + "" || null;
    }
    line.x = function(_2) {
      return arguments.length ? (x3 = typeof _2 === "function" ? _2 : constant_default2(+_2), line) : x3;
    };
    line.y = function(_2) {
      return arguments.length ? (y3 = typeof _2 === "function" ? _2 : constant_default2(+_2), line) : y3;
    };
    line.defined = function(_2) {
      return arguments.length ? (defined = typeof _2 === "function" ? _2 : constant_default2(!!_2), line) : defined;
    };
    line.curve = function(_2) {
      return arguments.length ? (curve = _2, context != null && (output = curve(context)), line) : curve;
    };
    line.context = function(_2) {
      return arguments.length ? (_2 == null ? context = output = null : output = curve(context = _2), line) : context;
    };
    return line;
  }

  // node_modules/d3-shape/src/curve/step.js
  function Step(context, t) {
    this._context = context;
    this._t = t;
  }
  Step.prototype = {
    areaStart: function() {
      this._line = 0;
    },
    areaEnd: function() {
      this._line = NaN;
    },
    lineStart: function() {
      this._x = this._y = NaN;
      this._point = 0;
    },
    lineEnd: function() {
      if (0 < this._t && this._t < 1 && this._point === 2) this._context.lineTo(this._x, this._y);
      if (this._line || this._line !== 0 && this._point === 1) this._context.closePath();
      if (this._line >= 0) this._t = 1 - this._t, this._line = 1 - this._line;
    },
    point: function(x3, y3) {
      x3 = +x3, y3 = +y3;
      switch (this._point) {
        case 0:
          this._point = 1;
          this._line ? this._context.lineTo(x3, y3) : this._context.moveTo(x3, y3);
          break;
        case 1:
          this._point = 2;
        // falls through
        default: {
          if (this._t <= 0) {
            this._context.lineTo(this._x, y3);
            this._context.lineTo(x3, y3);
          } else {
            var x1 = this._x * (1 - this._t) + x3 * this._t;
            this._context.lineTo(x1, this._y);
            this._context.lineTo(x1, y3);
          }
          break;
        }
      }
      this._x = x3, this._y = y3;
    }
  };
  function stepAfter(context) {
    return new Step(context, 1);
  }

  // src/analytics.ts
  var money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(value);
  var node = (tag, text = "", className = "") => {
    const el = document.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
  };
  var svgNode = (tag, attrs = {}, text = "") => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
    el.textContent = text;
    return el;
  };
  var Analytics = class {
    constructor(el) {
      this.el = el;
      __publicField(this, "dead", false);
      __publicField(this, "observer", null);
      __publicField(this, "redraw", null);
    }
    clear() {
      this.observer?.disconnect();
      this.observer = null;
      this.redraw = null;
      this.el.replaceChildren();
    }
    lines(curves, options = {}) {
      this.clear();
      this.el.classList.remove("comparison");
      const legend = node("div", "", "analytics-legend");
      for (const curve of curves) {
        const label = node("span", curve.label);
        const swatch = node("i");
        swatch.style.background = curve.color;
        label.prepend(swatch);
        legend.append(label);
      }
      this.el.append(legend);
      if (options.snapshot) {
        const snapshot = node("div", "", "equity-snapshot");
        snapshot.append(node("span", options.snapshot.label), node("strong", money(options.snapshot.value)));
        this.el.append(snapshot);
      }
      if (options.note) this.el.append(node("div", options.note, "analytics-note"));
      const clean = curves.map((c2) => ({ ...c2, data: [...new Map(c2.data.filter((p2) => Number.isFinite(+p2[0]) && Number.isFinite(p2[1])).map((p2) => [+p2[0], p2[1]])).entries()].sort((a2, b2) => a2[0] - b2[0]) }));
      const all = clean.flatMap((c2) => c2.data);
      if (options.percent && all.length && all.every((p2) => p2[1] === 0)) {
        this.el.append(node("div", "No drawdown in the recorded history.", "analytics-empty"));
        return;
      }
      if (!all.length) {
        this.el.append(node("div", options.empty || "History not available yet", "analytics-empty"));
        return;
      }
      const plot = node("div", "", "analytics-plot");
      this.el.append(plot);
      const valueLabel = options.percent ? (v2) => v2.toFixed(2) + "%" : money;
      this.redraw = () => {
        const width = plot.clientWidth, height = plot.clientHeight;
        if (width < 100 || height < 60) return;
        plot.replaceChildren();
        const left = 8, right = width - 76, top = 12, bottom = height - 32;
        let minTime = Math.min(...all.map((p2) => p2[0])), maxTime = Math.max(...all.map((p2) => p2[0]));
        if (minTime === maxTime) {
          minTime -= 864e5;
          maxTime += 864e5;
        }
        let min = Math.min(...all.map((p2) => p2[1])), max = Math.max(...all.map((p2) => p2[1]));
        if (options.percent) max = Math.max(0, max);
        const pad2 = Math.max((max - min) * 0.12, options.percent ? 0.01 : Math.max(Math.abs(max) * 5e-4, 0.01));
        const x3 = time().domain([new Date(minTime), new Date(maxTime)]).range([left, right]);
        const y3 = linear2().domain([min - pad2, options.percent ? Math.min(0, max) : max + pad2]).nice(4).range([bottom, top]);
        const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": `${curves.map((c2) => c2.label).join(", ")} over time` });
        svg.append(svgNode("title", {}, "Historical observations. Hover to inspect a date. Current equity is shown separately."));
        for (const value of y3.ticks(4)) {
          const py = y3(value);
          svg.append(svgNode("line", { x1: left, x2: right, y1: py, y2: py, stroke: "#edf1f4" }));
          svg.append(svgNode("text", { x: right + 12, y: py + 4, fill: "#61717f", "font-size": 12 }, valueLabel(value)));
        }
        const count = width < 450 ? 3 : 5;
        for (let i = 0; i < count; i++) {
          const time2 = minTime + (maxTime - minTime) * i / (count - 1);
          svg.append(svgNode("text", { x: x3(time2), y: height - 6, fill: "#61717f", "font-size": 12, "text-anchor": i === 0 ? "start" : i === count - 1 ? "end" : "middle" }, new Date(time2).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })));
        }
        for (const curve of clean) {
          const path2 = line_default().x((p2) => x3(p2[0])).y((p2) => y3(p2[1])).curve(curve.step ? stepAfter : linear_default)(curve.data);
          if (path2) svg.append(svgNode("path", { d: path2, fill: "none", stroke: curve.color, "stroke-width": 2, "data-series": curve.label }));
          if (curve.data.length === 1) svg.append(svgNode("circle", { cx: x3(curve.data[0][0]), cy: y3(curve.data[0][1]), r: 3, fill: curve.color }));
        }
        const cross = svgNode("line", { x1: left, x2: left, y1: top, y2: bottom, stroke: "#9ba8b3", "stroke-dasharray": "3 3", visibility: "hidden" });
        svg.append(cross);
        const tooltip = node("div", "", "analytics-tooltip");
        tooltip.hidden = true;
        plot.append(svg, tooltip);
        svg.addEventListener("pointermove", (event) => {
          const px = Math.max(left, Math.min(right, event.clientX - svg.getBoundingClientRect().left));
          const time2 = +x3.invert(px);
          cross.setAttribute("x1", String(px));
          cross.setAttribute("x2", String(px));
          cross.setAttribute("visibility", "visible");
          const values = clean.map((c2) => {
            const eligible = c2.data.filter((p3) => p3[0] <= time2);
            const p2 = eligible[eligible.length - 1];
            return p2 ? `${c2.label}: ${valueLabel(p2[1])}` : "";
          }).filter(Boolean);
          tooltip.textContent = [new Date(time2).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }), ...values].join(" \xB7 ");
          tooltip.hidden = false;
        });
        svg.addEventListener("pointerleave", () => {
          cross.setAttribute("visibility", "hidden");
          tooltip.hidden = true;
        });
      };
      this.observer = new ResizeObserver(() => this.redraw?.());
      this.observer.observe(plot);
      this.redraw();
    }
    comparison(rows) {
      this.clear();
      this.el.classList.add("comparison");
      if (!rows.length) {
        this.el.append(node("div", "No performance data yet", "analytics-empty"));
        return;
      }
      const table = node("table", "", "contribution-table");
      const head = node("thead");
      const tr2 = node("tr");
      for (const title of ["Name", "Realized", "Open P&L", "Total"]) tr2.append(node("th", title));
      head.append(tr2);
      table.append(head);
      const body = node("tbody");
      for (const row of rows) {
        const tr3 = node("tr");
        tr3.append(node("th", row.label));
        for (const value of [row.realized, row.unrealized, row.realized + row.unrealized]) tr3.append(node("td", money(value), value < 0 ? "neg" : value > 0 ? "pos" : ""));
        body.append(tr3);
      }
      table.append(body);
      this.el.append(table);
    }
    getDom() {
      return this.el;
    }
    isDisposed() {
      return this.dead;
    }
    resize() {
      this.redraw?.();
    }
    dispose() {
      this.dead = true;
      this.clear();
    }
  };
  window.TradingAnalytics = Analytics;

  // src/price-chart.ts
  var PriceChart = class {
    constructor(el) {
      this.el = el;
      __publicField(this, "chart");
      __publicField(this, "series");
      __publicField(this, "lines", []);
      __publicField(this, "timeframe", "");
      __publicField(this, "dead", false);
      __publicField(this, "exits", []);
      __publicField(this, "mode", "price");
      __publicField(this, "markers");
      __publicField(this, "entryIndex", -1);
      this.chart = Wn(el, { autoSize: true, localization: { locale: "en-US" }, layout: { background: { type: Li.Solid, color: "#ffffff" }, textColor: "#526170", fontSize: 12, attributionLogo: true }, grid: { vertLines: { visible: false }, horzLines: { color: "#edf0f2" } }, rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.12 } }, timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 4 }, crosshair: { mode: 0 } });
      this.series = this.chart.addSeries(Pe, { upColor: "#16714b", downColor: "#c23b35", borderVisible: false, wickUpColor: "#16714b", wickDownColor: "#c23b35", lastValueVisible: false, priceLineVisible: false, autoscaleInfoProvider: ((original) => {
        const info = original();
        if (!info?.priceRange || this.mode !== "exits") return info;
        for (const x3 of this.exits) {
          info.priceRange.minValue = Math.min(info.priceRange.minValue, x3.price);
          info.priceRange.maxValue = Math.max(info.priceRange.maxValue, x3.price);
        }
        return info;
      }) });
      this.markers = ur(this.series, []);
    }
    render(rows, trade, tf, mode) {
      const data = rows.filter((r2) => r2.length >= 5 && r2.every(Number.isFinite)).map((r2) => ({ time: Math.floor(r2[0] / 1e3), open: r2[1], close: r2[2], low: r2[3], high: r2[4] })).sort((a2, b2) => a2.time - b2.time).filter((r2, i, a2) => !i || r2.time !== a2[i - 1].time);
      if (!data.length) return;
      const previous = this.chart.timeScale().getVisibleLogicalRange();
      this.mode = mode;
      this.exits = [{ price: trade.open_rate, label: "Entry price", state: "entry" }, { price: trade.close_rate, label: trade.is_open ? "Current" : "Exit" }, ...trade.is_open && trade.stop_rate ? [{ price: trade.stop_rate, label: trade.is_open ? "Bot stop" : "Recorded stop", state: "stop" }] : [], ...trade.exit_levels || []].filter((x3) => Number.isFinite(x3.price) && x3.price > 0);
      const reference = data[data.length - 1].close;
      const precision = Math.min(10, Math.max(2, 4 - Math.floor(Math.log10(reference))));
      this.series.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
      this.series.setData(data);
      this.lines.forEach((line) => this.series.removePriceLine(line));
      this.lines = this.exits.map((x3) => this.series.createPriceLine({ price: x3.price, title: x3.label, axisLabelVisible: true, color: x3.state === "entry" ? "#176c84" : x3.state === "stop" ? "#c23b35" : x3.state === "active" ? "#16714b" : x3.state === "pending" ? "#9a690a" : "#657482", lineStyle: x3.state === "entry" || x3.state === "active" ? h.Solid : h.Dotted, lineWidth: x3.state === "entry" ? 2 : 1 }));
      const raw = trade.open_ts;
      const numeric = Number(raw);
      const opened = raw == null ? NaN : Number.isFinite(numeric) ? numeric < 1e12 ? numeric * 1e3 : numeric : Date.parse(String(raw));
      const seconds2 = opened / 1e3;
      const duration = { "5m": 300, "15m": 900, "1h": 3600, "4h": 14400 }[tf];
      const candle = duration && Number.isFinite(seconds2) ? data.find((r2) => r2.time <= seconds2 && seconds2 < r2.time + duration) : void 0;
      this.entryIndex = candle ? data.indexOf(candle) : -1;
      this.markers.setMarkers(candle ? [{ time: candle.time, position: trade.is_short ? "aboveBar" : "belowBar", shape: trade.is_short ? "arrowDown" : "arrowUp", color: "#176c84", text: "Entry", size: 1.5 }] : []);
      if (previous && this.timeframe === tf) this.chart.timeScale().setVisibleLogicalRange(previous);
      else this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.length - 90), to: data.length + 3 });
      this.timeframe = tf;
    }
    focusEntry() {
      if (this.entryIndex < 0) return false;
      this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, this.entryIndex - 12), to: this.entryIndex + 12 });
      return true;
    }
    getDom() {
      return this.el;
    }
    isDisposed() {
      return this.dead;
    }
    resize() {
      if (!this.dead) this.chart.resize(this.el.clientWidth, this.el.clientHeight);
    }
    dispose() {
      this.dead = true;
      this.chart.remove();
    }
  };
  window.TradingPriceChart = PriceChart;
})();
/*! Bundled license information:

lightweight-charts/dist/lightweight-charts.production.mjs:
  (*!
   * @license
   * TradingView Lightweight Charts™ v5.0.9
   * Copyright (c) 2025 TradingView, Inc.
   * Licensed under Apache License 2.0 https://www.apache.org/licenses/LICENSE-2.0
   *)
*/
