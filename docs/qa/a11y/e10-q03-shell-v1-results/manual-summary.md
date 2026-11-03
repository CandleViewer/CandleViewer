sha trees apps=f316c1ddd6a3 docs/plan/a11y/_tools=ef1175fe6eff (identical to the PR head); records 1233; results.json.gz sha256 a50f8ef993861d3bc3f473b7d1055ef260ce22222fe6c7f04467db81bf1c27f0

| check file             | records | pass | fail | not applicable / not built | ms    |
| ---------------------- | ------- | ---- | ---- | -------------------------- | ----- |
| keyboard-walk          | 366     | 366  | 0    | 0                          | 45252 |
| keyboard-esc           | 66      | 60   | 0    | 6                          | 16099 |
| keyboard-overlay-focus | 30      | 30   | 0    | 0                          | 14724 |
| zoom                   | 576     | 576  | 0    | 0                          | 70798 |
| greyscale              | 132     | 132  | 0    | 0                          | 19061 |
| names                  | 37      | 18   | 0    | 19                         | 3659  |
| token-audit            | 13      | 13   | 0    | 0                          | 5998  |
| announce               | 4       | 4    | 0    | 0                          | 703   |
| control-trap           | 2       | 2    | 0    | 0                          | 469   |
| control-clip-hue       | 4       | 4    | 0    | 0                          | 527   |
| control-focus          | 3       | 3    | 0    | 0                          | 325   |

```text
8b65b3349728e95881e55fc12d350e2ede032584992c5ad55186cb66fe24fba4  checks/keyboard-walk.json
9d75944f6280fad93db9dfd4794d8739711c932182744da38c59061d69c6499d  checks/keyboard-esc.json
5eddb19d651c842bbefd987f8994c3a73d5c95deddfde375a880dffa4c9691f6  checks/keyboard-overlay-focus.json
fa62dca201b6b4802911fe0861c7484a7e0c673aea9422e329afb0edb446132a  checks/zoom.json
43f8bdd18145c360f2855a35ef51b78a232260df0fdac7cc8d32aaccef0cb224  checks/greyscale.json
08ff515bfb06830ac2d853066c26410a5d3c298abcbd1c404d9f416e0d4b7378  checks/names.json
6108f4aa26b5b6f6f5d63f705b8c622382de567afa152585aad02ff42d0c7d45  checks/token-audit.json
ca78e2f61b8df5271583aca2164a86f26cb624b9696ed0383acc8769b4d7b85b  checks/announce.json
4ed12cc82acf18153a77246b68bcf03a62fbbb8e8750ab811a9f312dff6d79d2  checks/control-trap.json
bb9895c5bb682d991a1fa3fc3a61bf335b1ac094c442c34bf14c86086d50fff6  checks/control-clip-hue.json
60b6490759bf3f7b07a0e174e08ca6de95001aa70f330d99df07eac7c07b82a4  checks/control-focus.json
9342c97a448a7231e2adda6f0f6809afa0978d4e6b1f049342e875a46e0daa4d  checks/greyscale/chrome-live-dark-comfortable.png
abf7c89ad5c5ad2126ca83dd286158d4a93e1f679f5b6873dada3883c67aee32  checks/greyscale/chrome-live-dark-compact.png
8c989c2a14b31486dd33d8a4beba7ed0b95eae8ddc12a6ac55027354dd4e022b  checks/greyscale/chrome-live-high-contrast-comfortable.png
1506c346d0d33dc276cfd7a6886b6c63ec46ae7456f290c258b25f722348991c  checks/greyscale/chrome-live-high-contrast-compact.png
dbc34f80d163f3b5ce260b0338ff53afd5d3e10191a92bdee3ab96fa51822146  checks/greyscale/chrome-live-light-comfortable.png
d7e7c216a5b2d6fc306f6691daa47698a3ee48b05ec0fec69a96ddca4eb64ffe  checks/greyscale/chrome-live-light-compact.png
16d642ba9d5f6bbbc528ebec164258b889356559376f2bd9043d41471cd551c0  checks/greyscale/chrome-owner-dark-comfortable.png
78b8400d6d82a373c434dd7979bea5f6854ff44df4f5b79d6e524d0d0df0e4a3  checks/greyscale/chrome-owner-dark-compact.png
6e41b0bfe1cc3f5e9499b8eb3e8c0f7424e9ba11ea6c6b1775f2d3692facc615  checks/greyscale/chrome-owner-high-contrast-comfortable.png
e65b25d5820a392b47758a6c38abfc7c0bd4484030acbfdda1d59739c27104b7  checks/greyscale/chrome-owner-high-contrast-compact.png
8c5bf7ceddcfdfaf7c2d6b7f138881a7c6177cc85b41c3de6dc87ddf3b0287f6  checks/greyscale/chrome-owner-light-comfortable.png
492c4f05e52f4cea81281ed10af8f2ebdd3f22ade6e0e52e325ac1dce1a99220  checks/greyscale/chrome-owner-light-compact.png
512638d3eb6c0ba355b2a6f8c3894a4e13e1cc67e78dfb167bbeaf615dd3be1a  checks/greyscale/connection-down-dark-comfortable.png
e4d4401e8f9481d0cf56afd59e337282536901303acb8a060586f5f5a4af935b  checks/greyscale/connection-down-dark-compact.png
96d66ed94dedbf3d4be4a35169b1cc5f45ca786e85487ef4189ea9438543ce32  checks/greyscale/connection-down-high-contrast-comfortable.png
55633356856e87c185587d829d843984bbfa0fd60af4221794c2cfe085ff232a  checks/greyscale/connection-down-high-contrast-compact.png
754af5f5cfd74e44fd7b84eb5140084606c02fdea31d7ff7511c2384c52a1bb9  checks/greyscale/connection-down-light-comfortable.png
b40da3e7a4eced29476d7ca4586d3ba495aa7cef0020688433541d15191622c9  checks/greyscale/connection-down-light-compact.png
3dc424c73553fa01db8343ba8c18d0668ea6606c614467d837347f3256233d22  checks/greyscale/degraded-banner-dark-comfortable.png
33b76e086c773afe110d2d06731a468f48376edb52282114a9ff3e2ad0d383d8  checks/greyscale/degraded-banner-dark-compact.png
13a3f3d056655e8c0f9396067c7ba07c5625564f6d72925c517e2dc97c57290d  checks/greyscale/degraded-banner-high-contrast-comfortable.png
a5e55346080884ae2f598dbd46e6059b422dbc4754c5189b097a5e6c386306f8  checks/greyscale/degraded-banner-high-contrast-compact.png
a4e22c25a57bfff847f3a14ff3015411e6189ef24a8e483c65ab4235cf9337d4  checks/greyscale/degraded-banner-light-comfortable.png
86bf369801e731de807cc350757a420ea89037d54442eb1fc3ed2e8302921f82  checks/greyscale/degraded-banner-light-compact.png
af0f1a5c3424752f496435c050bd475b62a059bdcda321a2ea76101a90f46bde  checks/greyscale/version-banner-dark-comfortable.png
4eb01a3350e19b1f1e74286a2bb510934ab837a614feb195a97c8ea6fb10e575  checks/greyscale/version-banner-dark-compact.png
f8a5509f2cfb0a4f39ca987d62f9dd44244045130a5eed65b61479b7525c6381  checks/greyscale/version-banner-high-contrast-comfortable.png
509fd8aae8fad32493570a470d62ae09e050256e540e1831448ce70b9f713b00  checks/greyscale/version-banner-high-contrast-compact.png
ede59f87a32c92ab45e8c03e9a168c3d8a762e0bd9f210249aa12ba39a529472  checks/greyscale/version-banner-light-comfortable.png
44cfa5b6b74962b251717104158359d54ecd69aa4499c4750fd767ae942b0a59  checks/greyscale/version-banner-light-compact.png
ab8147120428184b60d236e80733a0806dc33e975b1b246c7896f78323e8b2bc  checks/designer/badge-chrome-live-dark-comfortable.png
ab8147120428184b60d236e80733a0806dc33e975b1b246c7896f78323e8b2bc  checks/designer/badge-chrome-live-dark-compact.png
90e2c93aa84246687797e326c1ca65e61d6fe417cde567a2c3441105f2503410  checks/designer/badge-chrome-live-high-contrast-comfortable.png
90e2c93aa84246687797e326c1ca65e61d6fe417cde567a2c3441105f2503410  checks/designer/badge-chrome-live-high-contrast-compact.png
aeedea7cd66a1ab6998466dbe3507ecd6c62bf67f0f39cbde0fca3286660eb99  checks/designer/badge-chrome-live-light-comfortable.png
aeedea7cd66a1ab6998466dbe3507ecd6c62bf67f0f39cbde0fca3286660eb99  checks/designer/badge-chrome-live-light-compact.png
d1230a08b90e45925d9558b91d8fb1d12c06dc14352e5119f430e325d0e70355  checks/designer/badge-chrome-owner-dark-comfortable.png
d1230a08b90e45925d9558b91d8fb1d12c06dc14352e5119f430e325d0e70355  checks/designer/badge-chrome-owner-dark-compact.png
8df57c9da149dbdf7ad8877362841f2657cd5cc3f599ba80449472ae027e1edf  checks/designer/badge-chrome-owner-high-contrast-comfortable.png
8df57c9da149dbdf7ad8877362841f2657cd5cc3f599ba80449472ae027e1edf  checks/designer/badge-chrome-owner-high-contrast-compact.png
0f3ce037656d5055d81db6306c28e8117c1fe69f084fa8ab10f6a673212e6479  checks/designer/badge-chrome-owner-light-comfortable.png
0f3ce037656d5055d81db6306c28e8117c1fe69f084fa8ab10f6a673212e6479  checks/designer/badge-chrome-owner-light-compact.png
```

no failed record
