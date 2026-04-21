# 分布式性能测试汇总报告

生成时间: Tue 21 Apr 2026 04:18:13 CST

## 测试配置

- 集群规模: 3,5,7
- 场景: same-region,cross-region
- 写操作数: 500
- 监控时长: 300s
- 监控启用: true

## 测试结果

### distributed_benchmark_20260421_041701.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,3,cross-region,1.4821549996117356,804.1154999955324,862.8088749974268,918.9272079966031,1.3639815455136501,0,0,0,0,0,3,3,0,2026-04-21T04:03:19.488435
tcp,3,cross-region,1.5523197514457283,633.2680420018733,657.5654999905964,692.8315419936553,1.7700686604062046,0,0,0,0,0,1,1,0,2026-04-21T04:16:09.971199
```

### distributed_benchmark_20260421_041609.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,5,same-region,1.5531656077648321,563.0692499980796,593.5368329955963,636.6027500043856,1.7788295003062349,0,0,0,0,0,17,17,0,2026-04-21T04:03:09.267366
tcp,5,same-region,1.7786279761794597,564.2660840094322,586.772334005218,599.704207998002,1.7687808282418078,0,0,0,0,0,0,0,0,2026-04-21T04:15:18.059478
```

### distributed_benchmark_20260421_041802.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,7,cross-region,1.4381640840285557,556.0753330064472,648.2578750001267,663.2672080013435,1.7757106648293175,0,0,0,0,0,3,3,0,2026-04-21T04:04:23.686676
tcp,7,cross-region,1.5943096321506822,626.4200419973349,649.9044590018457,657.5092499988386,1.775673645015868,0,0,0,0,0,0,0,0,2026-04-21T04:17:05.124908
```

### distributed_benchmark_20260421_041733.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,7,same-region,1.4597766487461952,565.1511249889154,590.4332909994991,635.0141250004526,1.7758928524665327,0,0,0,0,0,19,19,0,2026-04-21T04:04:18.939403
tcp,7,same-region,1.7716111871567135,562.9274579987396,587.1846660011215,602.0972919941414,1.7701573845114085,0,0,0,0,0,0,0,0,2026-04-21T04:16:29.222633
```

### distributed_benchmark_20260421_041449.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,3,same-region,1.6048365597020715,564.5329999970272,590.8138750091894,636.1932500003604,1.7800178255239811,0,0,0,0,0,15,15,0,2026-04-21T04:01:50.016302
tcp,3,same-region,1.7731539853347973,558.9684579899767,588.1196250120411,598.8892910099821,1.7757512168324816,0,0,0,0,0,0,0,0,2026-04-21T04:13:58.975639
```

### distributed_benchmark_20260421_041753.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,write_error_503,write_error_500,write_error_timeout,write_error_other,write_retries,write_retry_recovered,read_errors,timestamp
quic,5,cross-region,1.4512852799043543,629.9510840035509,713.5981659957906,817.120084000635,1.3663031660132978,0,0,0,0,0,7,7,0,2026-04-21T04:04:07.441846
tcp,5,cross-region,1.5857001429986575,628.174792000209,651.6944589966442,660.8159169991268,1.7732437265009198,0,0,0,0,0,0,0,0,2026-04-21T04:16:50.587548
```

## 监控数据

- metrics_node3_system_20260421_035244
- metrics_node1_raft_20260421_035244
- metrics_node2_system_20260421_035244
- metrics_node1_tcp_bench_20260421_035244
- metrics_node1_quic_bench_20260421_035244
- metrics_node1_network_20260421_035244
- metrics_node2_raft_20260421_035244
- metrics_node2_quic_bench_20260421_035244
- metrics_node2_network_20260421_035244
- metrics_node2_tcp_bench_20260421_035244
- metrics_node3_network_20260421_035244
- metrics_node3_quic_bench_20260421_035244
- metrics_node3_raft_20260421_035244
- metrics_node1_system_20260421_035244
- metrics_node3_tcp_bench_20260421_035244
- metrics_node5_tcp_bench_20260421_035400
- metrics_node2_raft_20260421_035400
- metrics_node2_quic_bench_20260421_035400
- metrics_node2_network_20260421_035400
- metrics_node4_quic_bench_20260421_035400
- metrics_node2_tcp_bench_20260421_035400
- metrics_node3_network_20260421_035400
- metrics_node5_quic_bench_20260421_035400
- metrics_node4_tcp_bench_20260421_035400
- metrics_node3_quic_bench_20260421_035400
- metrics_node1_system_20260421_035400
- metrics_node3_raft_20260421_035400
- metrics_node3_tcp_bench_20260421_035400
- metrics_node4_system_20260421_035400
- metrics_node3_system_20260421_035400
- metrics_node5_network_20260421_035400
- metrics_node1_raft_20260421_035400
- metrics_node5_raft_20260421_035400
- metrics_node1_tcp_bench_20260421_035400
- metrics_node2_system_20260421_035400
- metrics_node1_quic_bench_20260421_035400
- metrics_node4_raft_20260421_035400
- metrics_node1_network_20260421_035400
- metrics_node5_system_20260421_035400
- metrics_node4_network_20260421_035400
- metrics_node4_system_20260421_035332
- metrics_node6_quic_bench_20260421_035332
- metrics_node5_raft_20260421_035332
- metrics_node7_tcp_bench_20260421_035332
- metrics_node1_raft_20260421_035332
- metrics_node5_network_20260421_035332
- metrics_node3_system_20260421_035332
- metrics_node4_raft_20260421_035332
- metrics_node1_quic_bench_20260421_035332
- metrics_node2_system_20260421_035332
- metrics_node7_quic_bench_20260421_035332
- metrics_node1_tcp_bench_20260421_035332
- metrics_node4_network_20260421_035332
- metrics_node5_system_20260421_035332
- metrics_node1_network_20260421_035332
- metrics_node6_tcp_bench_20260421_035332
- metrics_node4_quic_bench_20260421_035332
- metrics_node2_network_20260421_035332
- metrics_node2_quic_bench_20260421_035332
- metrics_node7_network_20260421_035332
- metrics_node6_raft_20260421_035332
- metrics_node2_raft_20260421_035332
- metrics_node5_tcp_bench_20260421_035332
- metrics_node7_system_20260421_035332
- metrics_node2_tcp_bench_20260421_035332
- metrics_node3_quic_bench_20260421_035332
- metrics_node6_network_20260421_035332
- metrics_node4_tcp_bench_20260421_035332
- metrics_node6_system_20260421_035332
- metrics_node5_quic_bench_20260421_035332
- metrics_node3_network_20260421_035332
- metrics_node3_tcp_bench_20260421_035332
- metrics_node3_raft_20260421_035332
- metrics_node1_system_20260421_035332
- metrics_node7_raft_20260421_035332
- metrics_node5_network_20260421_035323
- metrics_node3_system_20260421_035323
- metrics_node7_tcp_bench_20260421_035323
- metrics_node5_raft_20260421_035323
- metrics_node1_raft_20260421_035323
- metrics_node6_quic_bench_20260421_035323
- metrics_node4_system_20260421_035323
- metrics_node1_network_20260421_035323
- metrics_node6_tcp_bench_20260421_035323
- metrics_node4_network_20260421_035323
- metrics_node5_system_20260421_035323
- metrics_node1_quic_bench_20260421_035323
- metrics_node2_system_20260421_035323
- metrics_node7_quic_bench_20260421_035323
- metrics_node1_tcp_bench_20260421_035323
- metrics_node4_raft_20260421_035323
- metrics_node2_tcp_bench_20260421_035323
- metrics_node7_system_20260421_035323
- metrics_node7_network_20260421_035323
- metrics_node6_raft_20260421_035323
- metrics_node2_raft_20260421_035323
- metrics_node5_tcp_bench_20260421_035323
- metrics_node4_quic_bench_20260421_035323
- metrics_node2_network_20260421_035323
- metrics_node2_quic_bench_20260421_035323
- metrics_node3_raft_20260421_035323
- metrics_node1_system_20260421_035323
- metrics_node7_raft_20260421_035323
- metrics_node3_tcp_bench_20260421_035323
- metrics_node3_network_20260421_035323
- metrics_node6_network_20260421_035323
- metrics_node3_quic_bench_20260421_035323
- metrics_node4_tcp_bench_20260421_035323
- metrics_node6_system_20260421_035323
- metrics_node5_quic_bench_20260421_035323
- metrics_node1_raft_20260421_035240
- metrics_node3_system_20260421_035240
- metrics_node1_network_20260421_035240
- metrics_node1_quic_bench_20260421_035240
- metrics_node1_tcp_bench_20260421_035240
- metrics_node2_system_20260421_035240
- metrics_node2_tcp_bench_20260421_035240
- metrics_node2_network_20260421_035240
- metrics_node2_quic_bench_20260421_035240
- metrics_node2_raft_20260421_035240
- metrics_node3_tcp_bench_20260421_035240
- metrics_node1_system_20260421_035240
- metrics_node3_raft_20260421_035240
- metrics_node3_quic_bench_20260421_035240
- metrics_node3_network_20260421_035240
- metrics_node1_quic_bench_20260421_035352
- metrics_node2_system_20260421_035352
- metrics_node1_tcp_bench_20260421_035352
- metrics_node4_raft_20260421_035352
- metrics_node1_network_20260421_035352
- metrics_node4_network_20260421_035352
- metrics_node5_system_20260421_035352
- metrics_node4_system_20260421_035352
- metrics_node5_network_20260421_035352
- metrics_node3_system_20260421_035352
- metrics_node5_raft_20260421_035352
- metrics_node1_raft_20260421_035352
- metrics_node3_network_20260421_035352
- metrics_node3_quic_bench_20260421_035352
- metrics_node4_tcp_bench_20260421_035352
- metrics_node5_quic_bench_20260421_035352
- metrics_node3_raft_20260421_035352
- metrics_node1_system_20260421_035352
- metrics_node3_tcp_bench_20260421_035352
- metrics_node2_raft_20260421_035352
- metrics_node5_tcp_bench_20260421_035352
- metrics_node4_quic_bench_20260421_035352
- metrics_node2_network_20260421_035352
- metrics_node2_quic_bench_20260421_035352
- metrics_node2_tcp_bench_20260421_035352

## 详细分析

### 同区域 vs 跨区域性能差异

基于测试数据分析:
- 同区域延迟应该远低于跨区域
- 跨区域吞吐量预期下降5-10倍
- 网络延迟主要由地理距离决定

### TCP vs QUIC性能对比

预期结果:
- QUIC吞吐量应与TCP相当或更高
- QUIC延迟应低于或等于TCP
- 多流优势在高并发下体现

### 集群规模影响

分析点:
- 3节点: 基线性能
- 5节点: Raft开销增加(日志复制)
- 7节点: 选举时间和网络消息增加

