# 分布式性能测试汇总报告

生成时间: Mon Apr 20 16:17:48 CST 2026

## 测试配置

- 集群规模: 3,5,7
- 场景: same-region,cross-region
- 写操作数: 500
- 监控时长: 300s
- 监控启用: false

## 测试结果

### distributed_benchmark_20260420_152158.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,3,cross-region,0.3516079949531446,637.9462499971851,674.3466249972698,707.3572080043959,1.712240139638616,394,0,2026-04-20T15:06:39.370813
tcp,3,cross-region,1.3263953920296643,736.6820000024745,764.9719170003664,775.382833002368,1.3690080275503047,0,0,2026-04-20T15:21:08.307856
```

### distributed_benchmark_20260420_135537.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,3,same-region,0.3081503646339169,567.4677920032991,619.6433749937569,651.0310829980881,1.735209708336361,412,0,2026-04-20T13:42:33.533990
tcp,3,same-region,1.741525454537404,568.2495840010233,603.8226670061704,837.9602079949109,1.7674415392839522,0,0,2026-04-20T13:54:48.614619
```

### distributed_benchmark_20260420_142349.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,5,same-region,0.26682093590060413,563.1725409984938,578.401999999187,582.3554999951739,1.732940334740648,424,0,2026-04-20T14:09:48.276035
tcp,5,same-region,1.7329310482571816,570.238790998701,617.3797500014189,722.5304579988006,1.7276355177258467,0,0,2026-04-20T14:22:09.896464
```

### distributed_benchmark_20260420_145205.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,7,same-region,0.13458034547810935,572.3942920012632,605.080999994243,834.3137499978184,1.7173891134430297,461,0,2026-04-20T14:38:49.141482
tcp,7,same-region,1.7318982180797047,576.2511670036474,652.9065840004478,827.6709159981692,1.7079682758590604,0,0,2026-04-20T14:51:12.391730
```

### distributed_benchmark_20260420_161743.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,7,cross-region,0.2851304839578761,631.5947499970207,705.5752090018359,902.1572080018814,1.805875218544302,416,0,2026-04-20T16:04:36.188976
tcp,7,cross-region,1.803513476095236,540.3636249975534,579.622917000961,610.0309169996763,1.800016718203908,0,0,2026-04-20T16:16:38.925339
```

### distributed_benchmark_20260420_154925.csv

```
protocol,cluster_size,scenario,write_throughput,write_p50_ms,write_p95_ms,write_p99_ms,read_throughput,write_errors,read_errors,timestamp
quic,5,cross-region,0.250160502878414,612.6590420026332,636.8461249949178,638.4862909981166,1.809653595844696,427,0,2026-04-20T15:36:17.591070
tcp,5,cross-region,1.744090028525042,570.5498329989496,609.546624997165,1550.8840830007102,1.7564230484512928,0,0,2026-04-20T15:48:33.238185
```

## 监控数据


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

