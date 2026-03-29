const fs = require("fs");
const path = require("path");
const protobuf = require("../_external/amae-koromo-scripts/node_modules/protobufjs");
const { lq } = require("../_external/amae-koromo-scripts/majsoulPb");

function main() {
  const recordPath = process.argv[2];
  const outPath = process.argv[3];
  if (!recordPath || !outPath) {
    console.error("Usage: node decode_majsoul_record.js <recordData path> <output json>");
    process.exit(1);
  }

  const root = protobuf.Root.fromJSON(
    JSON.parse(fs.readFileSync(path.join(__dirname, "..", "_external", "amae-koromo-scripts", "majsoulPb.proto.json"), "utf8"))
  );
  const wrapper = lq.Wrapper.decode(fs.readFileSync(recordPath));
  const type = root.lookupType(wrapper.name);
  const payload = type.decode(wrapper.data);

  const records = [];
  if (payload.version >= 210715) {
    for (const action of payload.actions || []) {
      if (action.result && action.result.length) {
        records.push(action.result);
      }
    }
  } else {
    for (const item of payload.records || []) {
      records.push(item);
    }
  }

  const decoded = records.map((buf, index) => {
    const wrapped = lq.Wrapper.decode(buf);
    const innerType = root.lookupType(wrapped.name);
    const innerPayload = innerType.decode(wrapped.data);
    return {
      index,
      name: wrapped.name,
      payload: innerType.toObject(innerPayload, {
        longs: String,
        enums: String,
        bytes: String,
        defaults: false,
        arrays: true,
        objects: true,
      }),
    };
  });

  const out = {
    root_wrapper_name: wrapper.name,
    payload_version: payload.version,
    record_count: decoded.length,
    records: decoded,
  };
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
  console.log(outPath);
}

main();
