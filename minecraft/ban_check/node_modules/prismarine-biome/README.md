# prismarine-biome
[![NPM version](https://img.shields.io/npm/v/prismarine-biome.svg)](http://npmjs.com/package/prismarine-biome)
[![Build Status](https://github.com/PrismarineJS/prismarine-biome/workflows/CI/badge.svg)](https://github.com/PrismarineJS/prismarine-biome/actions?query=workflow%3A%22CI%22)

Represent a minecraft biome with its associated data

## Usage

```js
const registry = require('prismarine-registry')('1.8')
const Biome = require("prismarine-biome")(registry);

const ocean = new Biome(registry.biomesByName.ocean.id)
console.log(ocean)
```

## API

### Biome

#### biome.id

Numerical id.

#### biome.color

#### biome.height

#### biome.name

#### biome.rainfall

#### biome.temperature

## History

### 1.4.0
* [Update CI to Node 24 (#22)](https://github.com/PrismarineJS/prismarine-biome/commit/6f9421fee9ad03fa5585dc95241de6bef9a93ec8) (thanks @rom1504)
* [Fix publish workflow for trusted publishing (#21)](https://github.com/PrismarineJS/prismarine-biome/commit/5583a71b081463fb5efcd99386e672a7f6ddb71d) (thanks @rom1504)
* [Switch to trusted publishing via OIDC (#20)](https://github.com/PrismarineJS/prismarine-biome/commit/ff4ff73f8fe3d84aba987dfd111844023d6aa37f) (thanks @rom1504)
* [node 22 (#19)](https://github.com/PrismarineJS/prismarine-biome/commit/8523c8864884695bad858b990fdaf57eb19166b3) (thanks @rom1504)
* [Add command gh workflow allowing to use release command in comments (#18)](https://github.com/PrismarineJS/prismarine-biome/commit/019071c02ba2e1952b659b3f0b1145eb75c826ac) (thanks @rom1504)
* [Update to node 18.0.0 (#17)](https://github.com/PrismarineJS/prismarine-biome/commit/c2c4f84bf604e7fbc9bc041eca40ff53d52e8f1a) (thanks @rom1504)
* [Update package.json (#16)](https://github.com/PrismarineJS/prismarine-biome/commit/bdee39107ec736a3ffd295565b4a3657454ca7a5) (thanks @Epirito)
* [Bump standard from 16.0.4 to 17.0.0 (#15)](https://github.com/PrismarineJS/prismarine-biome/commit/72bbc2d11ad6f52efa6ba4036dff16ca26f0cc86) (thanks @dependabot[bot])

### 1.3.0

* Bump mcdata

### 1.2.1
* Handle registry without biome info

### 1.2.0
* support pregistry

### 1.1.2
* Update type definitions

### 1.1.1

* move standard to dev dep

### 1.1.0

* typescript definitions (thanks @IdanHo)

### 1.0.1

* bump mcdata

### 1.0.0

* bump mcdata major

### 0.1.0

* Import from mineflayer
