const fs = require("fs");
const path = require("path");

async function main() {
  const [token, oauthType, uuid, outputDir, urlBase] = process.argv.slice(2);
  if (!token || !uuid || !outputDir) {
    throw new Error(
      "Usage: node fetch_majsoul_record.js <access_token> <oauth_type> <game_uuid> <output_dir> [url_base]"
    );
  }

  process.env.ACCESS_TOKEN = token;
  process.env.OAUTH_TYPE = oauthType || "0";
  process.env.URL_BASE = urlBase || "https://mahjongsoul.game.yo-star.com/";

  const { createMajsoulConnection } = require("../_external/amae-koromo-scripts/majsoul");
  const conn = await createMajsoulConnection(process.env.ACCESS_TOKEN);
  const resp = await conn.rpcCall(".lq.Lobby.fetchGameRecord", {
    game_uuid: uuid,
    client_version_string: conn.clientVersionString,
  });

  if ((!resp.data && !resp.data_url) || !resp.head) {
    throw new Error(`No game data returned for ${uuid}`);
  }

  const recordData = resp.data_url
    ? Buffer.from(await (await fetch(resp.data_url)).arrayBuffer())
    : Buffer.from(resp.data);

  fs.mkdirSync(outputDir, { recursive: true });
  fs.writeFileSync(path.join(outputDir, `${uuid}.head.json`), JSON.stringify(resp.head, null, 2), "utf-8");
  fs.writeFileSync(path.join(outputDir, `${uuid}.recordData`), recordData);

  const result = {
    uuid,
    outputDir,
    headPath: path.join(outputDir, `${uuid}.head.json`),
    recordDataPath: path.join(outputDir, `${uuid}.recordData`),
    hasDataUrl: !!resp.data_url,
    clientVersionString: conn.clientVersionString,
  };
  console.log(JSON.stringify(result));
  process.exit(0);
}

main().catch((error) => {
  console.error(error?.stack || String(error));
  process.exit(1);
});
