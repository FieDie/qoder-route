import fs from "fs";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";

const WASM_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), "qoder_auth_wasm.wasm");
const PORT = 8123;

const buf = fs.readFileSync(WASM_PATH);

const heap = new Array(128).fill(undefined);
heap.push(undefined, null, true, false);
let heap_next = heap.length;
const getObject = (i) => heap[i];
function addHeapObject(o) { if (heap_next === heap.length) heap.push(heap.length + 1); heap[heap_next] = o; return heap_next++; }
function dropObject(i) { if (i < 132) return; heap[i] = heap_next; heap_next = i; }
function cloneObject(i) { return addHeapObject(heap[i]); }

let wasm = null;
const enc = new TextEncoder();
const dec = new TextDecoder();
const mem = () => new Uint8Array(wasm.memory.buffer);
const view = () => new DataView(wasm.memory.buffer);
const getStr = (p, l) => dec.decode(mem().subarray(p, p + l));

let GLOBAL_LEN = 0;
function passString(s) {
  const bytes = enc.encode(s);
  const ptr = wasm.__wbindgen_export2(bytes.length, 1);
  mem().set(bytes, ptr);
  GLOBAL_LEN = bytes.length;
  return ptr;
}

const glue = new Proxy({}, {
  get(t, prop) {
    const name = prop;
    if (name === "__wbindgen_object_drop_ref") return (i) => dropObject(i);
    if (name === "__wbindgen_object_clone_ref") return (i) => cloneObject(i);
    if (name.startsWith("__wbindgen_cast_")) return (a, b) => (typeof a === "number" && typeof b === "number" ? addHeapObject(getStr(a, b)) : a);
    if (name === "__wbg_crypto_38df2bab126b63dc") return () => addHeapObject(globalThis.crypto);
    if (name === "__wbg_getRandomValues_d49329ff89a07af1") return (a, b) => globalThis.crypto.getRandomValues(new Uint8Array(wasm.memory.buffer, a, b));
    if (name === "__wbg_getRandomValues_c44a50d8cfdaebeb") return (c, a) => getObject(c).getRandomValues(getObject(a));
    if (name === "__wbg_now_88621c9c9a4f3ffc") return () => Date.now();
    if (name.startsWith("__wbg_static_accessor_GLOBAL_THIS")) return () => addHeapObject(globalThis);
    if (name.startsWith("__wbg_static_accessor_SELF")) return () => addHeapObject(globalThis);
    if (name.startsWith("__wbg_static_accessor_GLOBAL")) return () => addHeapObject(globalThis);
    if (name.startsWith("__wbg_static_accessor_WINDOW")) return () => 0;
    if (name.startsWith("__wbg___wbindgen_throw")) return (a, b) => { throw new Error(getStr(a, b)); };
    if (name.includes("__wbindgen_is_undefined")) return (i) => getObject(i) === undefined;
    if (name.includes("__wbindgen_is_object")) return (i) => { const v = getObject(i); return typeof v === "object" && v !== null; };
    if (name.includes("__wbindgen_is_string")) return (i) => typeof getObject(i) === "string";
    if (name.includes("__wbindgen_is_function")) return (i) => typeof getObject(i) === "function";
    if (name === "__wbg_new_with_length_9cedd08484b73942") return (len) => addHeapObject(new Uint8Array(len));
    if (name === "__wbg_length_0c32cb8543c8e4c8") return (i) => getObject(i).length;
    if (name === "__wbg_new_99cabae501c0a8a0") return () => addHeapObject(new Map());
    if (name === "__wbg_Error_2e59b1b37a9a34c3") return (a, b) => addHeapObject(new Error(getStr(a, b)));
    if (name === "__wbg_set_08463b1df38a7e29") return (m, k, v) => addHeapObject(getObject(m).set(getObject(k), getObject(v)));
    if (name === "__wbg_prototypesetcall_3e05eb9545565046") return (h, d, l) => new Uint8Array(wasm.memory.buffer, h, d).set(getObject(l));
    if (name === "__wbg_subarray_0f98d3fb634508ad") return (i, a, b) => addHeapObject(getObject(i).subarray(a, b));
    if (name === "__wbg_call_d578befcc3145dee") return (fref, arg) => getObject(fref)(getObject(arg));
    if (name === "__wbg_process_44c7a14e11e9f69e") return () => addHeapObject(process);
    if (name === "__wbg_versions_276b2795b1c6a219") return () => addHeapObject(process.versions);
    if (name === "__wbg_node_84ea875411254db1") return () => addHeapObject(process.versions.node);
    if (name === "__wbg_require_b4edbdcf3e2a1ef0") return () => 0;
    if (name === "__wbg_msCrypto_bd5a034af96bcba6") return () => 0;
    return (...args) => addHeapObject({});
  },
});

const { instance } = await WebAssembly.instantiate(buf, { "./qoder_auth_wasm_bg.js": glue });
wasm = instance.exports;

const addStack = (n) => wasm.__wbindgen_add_to_stack_pointer(n);

function stackStringCall(fn, args) {
  const sp = addStack(-16);
  const ptrs = args.map((a) => { const p = passString(a); return [p, GLOBAL_LEN]; });
  fn(sp, ...ptrs.flat());
  const r0 = view().getInt32(sp + 0, true);
  const r1 = view().getInt32(sp + 4, true);
  const r2 = view().getInt32(sp + 8, true);
  const r3 = view().getInt32(sp + 12, true);
  addStack(16);
  if (r3) throw new Error("wasm call failed");
  return getStr(r0, r1);
}

const generateRuntimeAuthFields = (subsetJson) =>
  JSON.parse(stackStringCall(wasm.generate_runtime_auth_fields, [subsetJson]));

const decryptServerResponse = (payload) =>
  stackStringCall(wasm.decrypt_server_response, [payload]);

function newContext(machineId, cosyVersion, userInfoJson, clientMetaJson) {
  const sp = addStack(-16);
  const a = passString(machineId), al = GLOBAL_LEN;
  const b = passString(cosyVersion), bl = GLOBAL_LEN;
  const c = passString(userInfoJson), cl = GLOBAL_LEN;
  const d = passString(clientMetaJson), dl = GLOBAL_LEN;
  wasm.qodercontext_new(sp, a, al, b, bl, c, cl, d, dl);
  const r0 = view().getInt32(sp + 0, true);
  const r2 = view().getInt32(sp + 8, true);
  addStack(16);
  if (r2) throw new Error("qodercontext_new failed");
  return r0 >>> 0;
}

function prepareInferRequest(ctxPtr, baseUrl, bodyJson, modelKey, modelSource) {
  const sp = addStack(-16);
  const a = passString(baseUrl), al = GLOBAL_LEN;
  const b = passString(bodyJson), bl = GLOBAL_LEN;
  const c = passString(modelKey), cl = GLOBAL_LEN;
  const d = passString(modelSource), dl = GLOBAL_LEN;
  wasm.qodercontext_prepareInferRequest(sp, ctxPtr, a, al, b, bl, c, cl, d, dl);
  const r0 = view().getInt32(sp + 0, true);
  const r2 = view().getInt32(sp + 8, true);
  addStack(16);
  if (r2) throw new Error("prepareInferRequest failed");
  return r0 >>> 0;
}

function resultUrl(rr) {
  const sp = addStack(-16);
  wasm.requestresult_url(sp, rr);
  const p = view().getInt32(sp + 0, true);
  const l = view().getInt32(sp + 4, true);
  const s = getStr(p, l);
  addStack(16);
  return s;
}

function resultHeaders(rr) {
  const m = getObject(wasm.requestresult_headers(rr));
  return m instanceof Map ? Object.fromEntries(m) : m;
}

function resultBody(rr) {
  const sp = addStack(-16);
  wasm.requestresult_body(sp, rr);
  const p = view().getInt32(sp + 0, true);
  const l = view().getInt32(sp + 4, true);
  const bytes = mem().slice(p, p + l);
  addStack(16);
  return Buffer.from(bytes);
}

const COSY_VERSION = "1.1.17";
// Exact Qoder CLI 1.1.17 client identity.  The numeric string is a routing
// discriminator used by the signed inference context; "cli" here can leave
// newer catalog models on a legacy upstream node.
const CLIENT_META = JSON.stringify({ client_type: "5", business_product: "cli", business_type: "agent", scene: "assistant" });

const contexts = new Map();
const MAX_CONTEXTS = 128;

function freeContext(ctx) {
  if (ctx?.ptr) wasm.__wbg_qodercontext_free(ctx.ptr, 0);
}

function getContext(jt, uid, machineId) {
  // Keep contexts isolated by job token and router machine identity.
  const cacheKey = `${jt}\0${machineId}`;
  let ctx = contexts.get(cacheKey);
  if (ctx && ctx.uid === uid) {
    // Refresh insertion order so the Map doubles as a small LRU cache.
    contexts.delete(cacheKey);
    contexts.set(cacheKey, ctx);
    return ctx.ptr;
  }
  if (ctx) {
    contexts.delete(cacheKey);
    freeContext(ctx);
  }
  // Qoder CLI passes getUserInfoForAuth() to QoderContext, not the login/job
  // token record.  Keeping tokens in this JSON changes the generated infer
  // credentials and can route newer models through a legacy provider node.
  const runtimeIdentity = {
    uid,
    organization_tags: [],
    data_policy_agreed: true,
  };
  const raf = generateRuntimeAuthFields(JSON.stringify(runtimeIdentity));
  const userInfo = JSON.stringify({
    ...runtimeIdentity,
    encrypt_user_info: raf.encrypt_user_info || "",
    key: raf.key || "",
  });
  const ptr = newContext(machineId, COSY_VERSION, userInfo, CLIENT_META);
  while (contexts.size >= MAX_CONTEXTS) {
    const oldestKey = contexts.keys().next().value;
    const oldest = contexts.get(oldestKey);
    contexts.delete(oldestKey);
    freeContext(oldest);
  }
  contexts.set(cacheKey, { ptr, uid });
  return ptr;
}

const readBody = (req) => new Promise((res, rej) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => res(Buffer.concat(chunks)));
  req.on("error", rej);
});

const server = http.createServer(async (req, res) => {
  const send = (code, obj) => {
    const data = Buffer.from(JSON.stringify(obj));
    res.writeHead(code, { "Content-Type": "application/json", "Content-Length": data.length });
    res.end(data);
  };
  try {
    const raw = await readBody(req);
    const input = raw.length ? JSON.parse(raw.toString()) : {};

    if (req.url === "/infer" && req.method === "POST") {
      const { jt, uid, machine_id, base_url, body_json, model_key, model_source } = input;
      const ctx = getContext(jt, uid, machine_id);
      const rr = prepareInferRequest(ctx, base_url, body_json, model_key, model_source ?? "system");
      const out = { url: resultUrl(rr), headers: resultHeaders(rr), body_b64: resultBody(rr).toString("base64") };
      wasm.__wbg_requestresult_free(rr, 0);
      return send(200, out);
    }

    if (req.url === "/decrypt" && req.method === "POST") {
      try {
        return send(200, { plain: decryptServerResponse(input.payload) });
      } catch {
        return send(200, { plain: null });
      }
    }

    if (req.url === "/health") return send(200, { ok: true, contexts: contexts.size });

    send(404, { error: "not found" });
  } catch (e) {
    send(500, { error: String(e && e.message || e) });
  }
});

server.listen(PORT, "127.0.0.1", () => console.log(`signer on 127.0.0.1:${PORT}`));
