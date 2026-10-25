// Prints JS scores for texts given in a JSON file: node ml_parity.js in.json [model.json]
const fs = require("fs");
const ML = require("../ml.js");
const model = JSON.parse(fs.readFileSync(process.argv[3] || (__dirname + "/../models/injection_lr.json")));
const texts = JSON.parse(fs.readFileSync(process.argv[2]));
console.log(JSON.stringify(texts.map(t => ({ norm: ML.normalizerFor(model)(t), score: ML.score(model, t), judge: ML.judge(model, t).level }))));
