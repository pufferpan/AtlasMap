import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
globalThis.crypto ||= webcrypto;
import {importOwnerKey,normalizeMachine,issueLicense,base64url,decode} from '../dist/activation-crypto.mjs';
const body='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('DFM1:'+body)));
const check=Array.from(hash.slice(0,2),v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();
const machine='DFM1-'+body.match(/.{8}/g).join('-')+'-'+check;
test('machine checksum and copied whitespace',async()=>{
 assert.equal(await normalizeMachine(machine.toLowerCase()+'\n'),machine);
 await assert.rejects(normalizeMachine(machine.slice(0,-1)+'Z'));
 await assert.rejects(normalizeMachine('garbage'));
});
test('signed token verifies with matching public key and domain',async()=>{
 const keys=await crypto.subtle.generateKey('Ed25519',true,['sign','verify']);
 const pkcs8=new Uint8Array(await crypto.subtle.exportKey('pkcs8',keys.privateKey));
 const pub=new Uint8Array(await crypto.subtle.exportKey('raw',keys.publicKey));
 const pem='-----BEGIN PRIVATE KEY-----\n'+btoa(String.fromCharCode(...pkcs8))+'\n-----END PRIVATE KEY-----';
 const key=await importOwnerKey(pem,base64url(pub));assert.equal(key.extractable,false);
 const token=await issueLicense(key,machine,123);const [prefix,payload,signature]=token.split('.');
 assert.equal(prefix,'DFMA1');
 const message=new Uint8Array([...new TextEncoder().encode('AtlasMap license v1\0'),...decode(payload)]);
 assert.equal(await crypto.subtle.verify('Ed25519',keys.publicKey,decode(signature),message),true);
 assert.deepEqual(JSON.parse(new TextDecoder().decode(decode(payload))),{issued_at:123,machine,product:'AtlasMap',v:1});
 await assert.rejects(importOwnerKey(pem));
});
test('invalid key files are rejected',async()=>{
 await assert.rejects(importOwnerKey('not a key'));
});
