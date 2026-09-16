import {
    Cell,
    Slice,
    Address,
    Builder,
    beginCell,
    ComputeError,
    TupleItem,
    TupleReader,
    Dictionary,
    contractAddress,
    address,
    ContractProvider,
    Sender,
    Contract,
    ContractABI,
    ABIType,
    ABIGetter,
    ABIReceiver,
    TupleBuilder,
    DictionaryValue
} from '@ton/core';

export type DataSize = {
    $$type: 'DataSize';
    cells: bigint;
    bits: bigint;
    refs: bigint;
}

export function storeDataSize(src: DataSize) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.cells, 257);
        b_0.storeInt(src.bits, 257);
        b_0.storeInt(src.refs, 257);
    };
}

export function loadDataSize(slice: Slice) {
    const sc_0 = slice;
    const _cells = sc_0.loadIntBig(257);
    const _bits = sc_0.loadIntBig(257);
    const _refs = sc_0.loadIntBig(257);
    return { $$type: 'DataSize' as const, cells: _cells, bits: _bits, refs: _refs };
}

export function loadTupleDataSize(source: TupleReader) {
    const _cells = source.readBigNumber();
    const _bits = source.readBigNumber();
    const _refs = source.readBigNumber();
    return { $$type: 'DataSize' as const, cells: _cells, bits: _bits, refs: _refs };
}

export function loadGetterTupleDataSize(source: TupleReader) {
    const _cells = source.readBigNumber();
    const _bits = source.readBigNumber();
    const _refs = source.readBigNumber();
    return { $$type: 'DataSize' as const, cells: _cells, bits: _bits, refs: _refs };
}

export function storeTupleDataSize(source: DataSize) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.cells);
    builder.writeNumber(source.bits);
    builder.writeNumber(source.refs);
    return builder.build();
}

export function dictValueParserDataSize(): DictionaryValue<DataSize> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeDataSize(src)).endCell());
        },
        parse: (src) => {
            return loadDataSize(src.loadRef().beginParse());
        }
    }
}

export type SignedBundle = {
    $$type: 'SignedBundle';
    signature: Buffer;
    signedData: Slice;
}

export function storeSignedBundle(src: SignedBundle) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeBuffer(src.signature);
        b_0.storeBuilder(src.signedData.asBuilder());
    };
}

export function loadSignedBundle(slice: Slice) {
    const sc_0 = slice;
    const _signature = sc_0.loadBuffer(64);
    const _signedData = sc_0;
    return { $$type: 'SignedBundle' as const, signature: _signature, signedData: _signedData };
}

export function loadTupleSignedBundle(source: TupleReader) {
    const _signature = source.readBuffer();
    const _signedData = source.readCell().asSlice();
    return { $$type: 'SignedBundle' as const, signature: _signature, signedData: _signedData };
}

export function loadGetterTupleSignedBundle(source: TupleReader) {
    const _signature = source.readBuffer();
    const _signedData = source.readCell().asSlice();
    return { $$type: 'SignedBundle' as const, signature: _signature, signedData: _signedData };
}

export function storeTupleSignedBundle(source: SignedBundle) {
    const builder = new TupleBuilder();
    builder.writeBuffer(source.signature);
    builder.writeSlice(source.signedData.asCell());
    return builder.build();
}

export function dictValueParserSignedBundle(): DictionaryValue<SignedBundle> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeSignedBundle(src)).endCell());
        },
        parse: (src) => {
            return loadSignedBundle(src.loadRef().beginParse());
        }
    }
}

export type StateInit = {
    $$type: 'StateInit';
    code: Cell;
    data: Cell;
}

export function storeStateInit(src: StateInit) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeRef(src.code);
        b_0.storeRef(src.data);
    };
}

export function loadStateInit(slice: Slice) {
    const sc_0 = slice;
    const _code = sc_0.loadRef();
    const _data = sc_0.loadRef();
    return { $$type: 'StateInit' as const, code: _code, data: _data };
}

export function loadTupleStateInit(source: TupleReader) {
    const _code = source.readCell();
    const _data = source.readCell();
    return { $$type: 'StateInit' as const, code: _code, data: _data };
}

export function loadGetterTupleStateInit(source: TupleReader) {
    const _code = source.readCell();
    const _data = source.readCell();
    return { $$type: 'StateInit' as const, code: _code, data: _data };
}

export function storeTupleStateInit(source: StateInit) {
    const builder = new TupleBuilder();
    builder.writeCell(source.code);
    builder.writeCell(source.data);
    return builder.build();
}

export function dictValueParserStateInit(): DictionaryValue<StateInit> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeStateInit(src)).endCell());
        },
        parse: (src) => {
            return loadStateInit(src.loadRef().beginParse());
        }
    }
}

export type Context = {
    $$type: 'Context';
    bounceable: boolean;
    sender: Address;
    value: bigint;
    raw: Slice;
}

export function storeContext(src: Context) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeBit(src.bounceable);
        b_0.storeAddress(src.sender);
        b_0.storeInt(src.value, 257);
        b_0.storeRef(src.raw.asCell());
    };
}

export function loadContext(slice: Slice) {
    const sc_0 = slice;
    const _bounceable = sc_0.loadBit();
    const _sender = sc_0.loadAddress();
    const _value = sc_0.loadIntBig(257);
    const _raw = sc_0.loadRef().asSlice();
    return { $$type: 'Context' as const, bounceable: _bounceable, sender: _sender, value: _value, raw: _raw };
}

export function loadTupleContext(source: TupleReader) {
    const _bounceable = source.readBoolean();
    const _sender = source.readAddress();
    const _value = source.readBigNumber();
    const _raw = source.readCell().asSlice();
    return { $$type: 'Context' as const, bounceable: _bounceable, sender: _sender, value: _value, raw: _raw };
}

export function loadGetterTupleContext(source: TupleReader) {
    const _bounceable = source.readBoolean();
    const _sender = source.readAddress();
    const _value = source.readBigNumber();
    const _raw = source.readCell().asSlice();
    return { $$type: 'Context' as const, bounceable: _bounceable, sender: _sender, value: _value, raw: _raw };
}

export function storeTupleContext(source: Context) {
    const builder = new TupleBuilder();
    builder.writeBoolean(source.bounceable);
    builder.writeAddress(source.sender);
    builder.writeNumber(source.value);
    builder.writeSlice(source.raw.asCell());
    return builder.build();
}

export function dictValueParserContext(): DictionaryValue<Context> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeContext(src)).endCell());
        },
        parse: (src) => {
            return loadContext(src.loadRef().beginParse());
        }
    }
}

export type SendParameters = {
    $$type: 'SendParameters';
    mode: bigint;
    body: Cell | null;
    code: Cell | null;
    data: Cell | null;
    value: bigint;
    to: Address;
    bounce: boolean;
}

export function storeSendParameters(src: SendParameters) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.mode, 257);
        if (src.body !== null && src.body !== undefined) { b_0.storeBit(true).storeRef(src.body); } else { b_0.storeBit(false); }
        if (src.code !== null && src.code !== undefined) { b_0.storeBit(true).storeRef(src.code); } else { b_0.storeBit(false); }
        if (src.data !== null && src.data !== undefined) { b_0.storeBit(true).storeRef(src.data); } else { b_0.storeBit(false); }
        b_0.storeInt(src.value, 257);
        b_0.storeAddress(src.to);
        b_0.storeBit(src.bounce);
    };
}

export function loadSendParameters(slice: Slice) {
    const sc_0 = slice;
    const _mode = sc_0.loadIntBig(257);
    const _body = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _code = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _data = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _value = sc_0.loadIntBig(257);
    const _to = sc_0.loadAddress();
    const _bounce = sc_0.loadBit();
    return { $$type: 'SendParameters' as const, mode: _mode, body: _body, code: _code, data: _data, value: _value, to: _to, bounce: _bounce };
}

export function loadTupleSendParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _code = source.readCellOpt();
    const _data = source.readCellOpt();
    const _value = source.readBigNumber();
    const _to = source.readAddress();
    const _bounce = source.readBoolean();
    return { $$type: 'SendParameters' as const, mode: _mode, body: _body, code: _code, data: _data, value: _value, to: _to, bounce: _bounce };
}

export function loadGetterTupleSendParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _code = source.readCellOpt();
    const _data = source.readCellOpt();
    const _value = source.readBigNumber();
    const _to = source.readAddress();
    const _bounce = source.readBoolean();
    return { $$type: 'SendParameters' as const, mode: _mode, body: _body, code: _code, data: _data, value: _value, to: _to, bounce: _bounce };
}

export function storeTupleSendParameters(source: SendParameters) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.mode);
    builder.writeCell(source.body);
    builder.writeCell(source.code);
    builder.writeCell(source.data);
    builder.writeNumber(source.value);
    builder.writeAddress(source.to);
    builder.writeBoolean(source.bounce);
    return builder.build();
}

export function dictValueParserSendParameters(): DictionaryValue<SendParameters> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeSendParameters(src)).endCell());
        },
        parse: (src) => {
            return loadSendParameters(src.loadRef().beginParse());
        }
    }
}

export type MessageParameters = {
    $$type: 'MessageParameters';
    mode: bigint;
    body: Cell | null;
    value: bigint;
    to: Address;
    bounce: boolean;
}

export function storeMessageParameters(src: MessageParameters) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.mode, 257);
        if (src.body !== null && src.body !== undefined) { b_0.storeBit(true).storeRef(src.body); } else { b_0.storeBit(false); }
        b_0.storeInt(src.value, 257);
        b_0.storeAddress(src.to);
        b_0.storeBit(src.bounce);
    };
}

export function loadMessageParameters(slice: Slice) {
    const sc_0 = slice;
    const _mode = sc_0.loadIntBig(257);
    const _body = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _value = sc_0.loadIntBig(257);
    const _to = sc_0.loadAddress();
    const _bounce = sc_0.loadBit();
    return { $$type: 'MessageParameters' as const, mode: _mode, body: _body, value: _value, to: _to, bounce: _bounce };
}

export function loadTupleMessageParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _value = source.readBigNumber();
    const _to = source.readAddress();
    const _bounce = source.readBoolean();
    return { $$type: 'MessageParameters' as const, mode: _mode, body: _body, value: _value, to: _to, bounce: _bounce };
}

export function loadGetterTupleMessageParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _value = source.readBigNumber();
    const _to = source.readAddress();
    const _bounce = source.readBoolean();
    return { $$type: 'MessageParameters' as const, mode: _mode, body: _body, value: _value, to: _to, bounce: _bounce };
}

export function storeTupleMessageParameters(source: MessageParameters) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.mode);
    builder.writeCell(source.body);
    builder.writeNumber(source.value);
    builder.writeAddress(source.to);
    builder.writeBoolean(source.bounce);
    return builder.build();
}

export function dictValueParserMessageParameters(): DictionaryValue<MessageParameters> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeMessageParameters(src)).endCell());
        },
        parse: (src) => {
            return loadMessageParameters(src.loadRef().beginParse());
        }
    }
}

export type DeployParameters = {
    $$type: 'DeployParameters';
    mode: bigint;
    body: Cell | null;
    value: bigint;
    bounce: boolean;
    init: StateInit;
}

export function storeDeployParameters(src: DeployParameters) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.mode, 257);
        if (src.body !== null && src.body !== undefined) { b_0.storeBit(true).storeRef(src.body); } else { b_0.storeBit(false); }
        b_0.storeInt(src.value, 257);
        b_0.storeBit(src.bounce);
        b_0.store(storeStateInit(src.init));
    };
}

export function loadDeployParameters(slice: Slice) {
    const sc_0 = slice;
    const _mode = sc_0.loadIntBig(257);
    const _body = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _value = sc_0.loadIntBig(257);
    const _bounce = sc_0.loadBit();
    const _init = loadStateInit(sc_0);
    return { $$type: 'DeployParameters' as const, mode: _mode, body: _body, value: _value, bounce: _bounce, init: _init };
}

export function loadTupleDeployParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _value = source.readBigNumber();
    const _bounce = source.readBoolean();
    const _init = loadTupleStateInit(source);
    return { $$type: 'DeployParameters' as const, mode: _mode, body: _body, value: _value, bounce: _bounce, init: _init };
}

export function loadGetterTupleDeployParameters(source: TupleReader) {
    const _mode = source.readBigNumber();
    const _body = source.readCellOpt();
    const _value = source.readBigNumber();
    const _bounce = source.readBoolean();
    const _init = loadGetterTupleStateInit(source);
    return { $$type: 'DeployParameters' as const, mode: _mode, body: _body, value: _value, bounce: _bounce, init: _init };
}

export function storeTupleDeployParameters(source: DeployParameters) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.mode);
    builder.writeCell(source.body);
    builder.writeNumber(source.value);
    builder.writeBoolean(source.bounce);
    builder.writeTuple(storeTupleStateInit(source.init));
    return builder.build();
}

export function dictValueParserDeployParameters(): DictionaryValue<DeployParameters> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeDeployParameters(src)).endCell());
        },
        parse: (src) => {
            return loadDeployParameters(src.loadRef().beginParse());
        }
    }
}

export type StdAddress = {
    $$type: 'StdAddress';
    workchain: bigint;
    address: bigint;
}

export function storeStdAddress(src: StdAddress) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.workchain, 8);
        b_0.storeUint(src.address, 256);
    };
}

export function loadStdAddress(slice: Slice) {
    const sc_0 = slice;
    const _workchain = sc_0.loadIntBig(8);
    const _address = sc_0.loadUintBig(256);
    return { $$type: 'StdAddress' as const, workchain: _workchain, address: _address };
}

export function loadTupleStdAddress(source: TupleReader) {
    const _workchain = source.readBigNumber();
    const _address = source.readBigNumber();
    return { $$type: 'StdAddress' as const, workchain: _workchain, address: _address };
}

export function loadGetterTupleStdAddress(source: TupleReader) {
    const _workchain = source.readBigNumber();
    const _address = source.readBigNumber();
    return { $$type: 'StdAddress' as const, workchain: _workchain, address: _address };
}

export function storeTupleStdAddress(source: StdAddress) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.workchain);
    builder.writeNumber(source.address);
    return builder.build();
}

export function dictValueParserStdAddress(): DictionaryValue<StdAddress> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeStdAddress(src)).endCell());
        },
        parse: (src) => {
            return loadStdAddress(src.loadRef().beginParse());
        }
    }
}

export type VarAddress = {
    $$type: 'VarAddress';
    workchain: bigint;
    address: Slice;
}

export function storeVarAddress(src: VarAddress) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeInt(src.workchain, 32);
        b_0.storeRef(src.address.asCell());
    };
}

export function loadVarAddress(slice: Slice) {
    const sc_0 = slice;
    const _workchain = sc_0.loadIntBig(32);
    const _address = sc_0.loadRef().asSlice();
    return { $$type: 'VarAddress' as const, workchain: _workchain, address: _address };
}

export function loadTupleVarAddress(source: TupleReader) {
    const _workchain = source.readBigNumber();
    const _address = source.readCell().asSlice();
    return { $$type: 'VarAddress' as const, workchain: _workchain, address: _address };
}

export function loadGetterTupleVarAddress(source: TupleReader) {
    const _workchain = source.readBigNumber();
    const _address = source.readCell().asSlice();
    return { $$type: 'VarAddress' as const, workchain: _workchain, address: _address };
}

export function storeTupleVarAddress(source: VarAddress) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.workchain);
    builder.writeSlice(source.address.asCell());
    return builder.build();
}

export function dictValueParserVarAddress(): DictionaryValue<VarAddress> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeVarAddress(src)).endCell());
        },
        parse: (src) => {
            return loadVarAddress(src.loadRef().beginParse());
        }
    }
}

export type BasechainAddress = {
    $$type: 'BasechainAddress';
    hash: bigint | null;
}

export function storeBasechainAddress(src: BasechainAddress) {
    return (builder: Builder) => {
        const b_0 = builder;
        if (src.hash !== null && src.hash !== undefined) { b_0.storeBit(true).storeInt(src.hash, 257); } else { b_0.storeBit(false); }
    };
}

export function loadBasechainAddress(slice: Slice) {
    const sc_0 = slice;
    const _hash = sc_0.loadBit() ? sc_0.loadIntBig(257) : null;
    return { $$type: 'BasechainAddress' as const, hash: _hash };
}

export function loadTupleBasechainAddress(source: TupleReader) {
    const _hash = source.readBigNumberOpt();
    return { $$type: 'BasechainAddress' as const, hash: _hash };
}

export function loadGetterTupleBasechainAddress(source: TupleReader) {
    const _hash = source.readBigNumberOpt();
    return { $$type: 'BasechainAddress' as const, hash: _hash };
}

export function storeTupleBasechainAddress(source: BasechainAddress) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.hash);
    return builder.build();
}

export function dictValueParserBasechainAddress(): DictionaryValue<BasechainAddress> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeBasechainAddress(src)).endCell());
        },
        parse: (src) => {
            return loadBasechainAddress(src.loadRef().beginParse());
        }
    }
}

export type Deploy = {
    $$type: 'Deploy';
    queryId: bigint;
}

export function storeDeploy(src: Deploy) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(2490013878, 32);
        b_0.storeUint(src.queryId, 64);
    };
}

export function loadDeploy(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 2490013878) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    return { $$type: 'Deploy' as const, queryId: _queryId };
}

export function loadTupleDeploy(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'Deploy' as const, queryId: _queryId };
}

export function loadGetterTupleDeploy(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'Deploy' as const, queryId: _queryId };
}

export function storeTupleDeploy(source: Deploy) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    return builder.build();
}

export function dictValueParserDeploy(): DictionaryValue<Deploy> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeDeploy(src)).endCell());
        },
        parse: (src) => {
            return loadDeploy(src.loadRef().beginParse());
        }
    }
}

export type DeployOk = {
    $$type: 'DeployOk';
    queryId: bigint;
}

export function storeDeployOk(src: DeployOk) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(2952335191, 32);
        b_0.storeUint(src.queryId, 64);
    };
}

export function loadDeployOk(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 2952335191) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    return { $$type: 'DeployOk' as const, queryId: _queryId };
}

export function loadTupleDeployOk(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'DeployOk' as const, queryId: _queryId };
}

export function loadGetterTupleDeployOk(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'DeployOk' as const, queryId: _queryId };
}

export function storeTupleDeployOk(source: DeployOk) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    return builder.build();
}

export function dictValueParserDeployOk(): DictionaryValue<DeployOk> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeDeployOk(src)).endCell());
        },
        parse: (src) => {
            return loadDeployOk(src.loadRef().beginParse());
        }
    }
}

export type FactoryDeploy = {
    $$type: 'FactoryDeploy';
    queryId: bigint;
    cashback: Address;
}

export function storeFactoryDeploy(src: FactoryDeploy) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(1829761339, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeAddress(src.cashback);
    };
}

export function loadFactoryDeploy(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 1829761339) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _cashback = sc_0.loadAddress();
    return { $$type: 'FactoryDeploy' as const, queryId: _queryId, cashback: _cashback };
}

export function loadTupleFactoryDeploy(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _cashback = source.readAddress();
    return { $$type: 'FactoryDeploy' as const, queryId: _queryId, cashback: _cashback };
}

export function loadGetterTupleFactoryDeploy(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _cashback = source.readAddress();
    return { $$type: 'FactoryDeploy' as const, queryId: _queryId, cashback: _cashback };
}

export function storeTupleFactoryDeploy(source: FactoryDeploy) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeAddress(source.cashback);
    return builder.build();
}

export function dictValueParserFactoryDeploy(): DictionaryValue<FactoryDeploy> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeFactoryDeploy(src)).endCell());
        },
        parse: (src) => {
            return loadFactoryDeploy(src.loadRef().beginParse());
        }
    }
}

export type JettonTransferInternal = {
    $$type: 'JettonTransferInternal';
    queryId: bigint;
    amount: bigint;
    sender: Address;
    responseDestination: Address | null;
    forwardTonAmount: bigint;
    forwardPayload: Slice;
}

export function storeJettonTransferInternal(src: JettonTransferInternal) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(395134233, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeCoins(src.amount);
        b_0.storeAddress(src.sender);
        b_0.storeAddress(src.responseDestination);
        b_0.storeCoins(src.forwardTonAmount);
        b_0.storeBuilder(src.forwardPayload.asBuilder());
    };
}

export function loadJettonTransferInternal(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 395134233) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _amount = sc_0.loadCoins();
    const _sender = sc_0.loadAddress();
    const _responseDestination = sc_0.loadMaybeAddress();
    const _forwardTonAmount = sc_0.loadCoins();
    const _forwardPayload = sc_0;
    return { $$type: 'JettonTransferInternal' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function loadTupleJettonTransferInternal(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    const _forwardTonAmount = source.readBigNumber();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransferInternal' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function loadGetterTupleJettonTransferInternal(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    const _forwardTonAmount = source.readBigNumber();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransferInternal' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function storeTupleJettonTransferInternal(source: JettonTransferInternal) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeNumber(source.amount);
    builder.writeAddress(source.sender);
    builder.writeAddress(source.responseDestination);
    builder.writeNumber(source.forwardTonAmount);
    builder.writeSlice(source.forwardPayload.asCell());
    return builder.build();
}

export function dictValueParserJettonTransferInternal(): DictionaryValue<JettonTransferInternal> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonTransferInternal(src)).endCell());
        },
        parse: (src) => {
            return loadJettonTransferInternal(src.loadRef().beginParse());
        }
    }
}

export type JettonTransferNotification = {
    $$type: 'JettonTransferNotification';
    queryId: bigint;
    amount: bigint;
    sender: Address;
    forwardPayload: Slice;
}

export function storeJettonTransferNotification(src: JettonTransferNotification) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(1935855772, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeCoins(src.amount);
        b_0.storeAddress(src.sender);
        b_0.storeBuilder(src.forwardPayload.asBuilder());
    };
}

export function loadJettonTransferNotification(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 1935855772) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _amount = sc_0.loadCoins();
    const _sender = sc_0.loadAddress();
    const _forwardPayload = sc_0;
    return { $$type: 'JettonTransferNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, forwardPayload: _forwardPayload };
}

export function loadTupleJettonTransferNotification(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransferNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, forwardPayload: _forwardPayload };
}

export function loadGetterTupleJettonTransferNotification(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransferNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, forwardPayload: _forwardPayload };
}

export function storeTupleJettonTransferNotification(source: JettonTransferNotification) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeNumber(source.amount);
    builder.writeAddress(source.sender);
    builder.writeSlice(source.forwardPayload.asCell());
    return builder.build();
}

export function dictValueParserJettonTransferNotification(): DictionaryValue<JettonTransferNotification> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonTransferNotification(src)).endCell());
        },
        parse: (src) => {
            return loadJettonTransferNotification(src.loadRef().beginParse());
        }
    }
}

export type JettonTransfer = {
    $$type: 'JettonTransfer';
    queryId: bigint;
    amount: bigint;
    destination: Address;
    responseDestination: Address | null;
    customPayload: Cell | null;
    forwardTonAmount: bigint;
    forwardPayload: Slice;
}

export function storeJettonTransfer(src: JettonTransfer) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(260734629, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeCoins(src.amount);
        b_0.storeAddress(src.destination);
        b_0.storeAddress(src.responseDestination);
        if (src.customPayload !== null && src.customPayload !== undefined) { b_0.storeBit(true).storeRef(src.customPayload); } else { b_0.storeBit(false); }
        b_0.storeCoins(src.forwardTonAmount);
        b_0.storeBuilder(src.forwardPayload.asBuilder());
    };
}

export function loadJettonTransfer(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 260734629) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _amount = sc_0.loadCoins();
    const _destination = sc_0.loadAddress();
    const _responseDestination = sc_0.loadMaybeAddress();
    const _customPayload = sc_0.loadBit() ? sc_0.loadRef() : null;
    const _forwardTonAmount = sc_0.loadCoins();
    const _forwardPayload = sc_0;
    return { $$type: 'JettonTransfer' as const, queryId: _queryId, amount: _amount, destination: _destination, responseDestination: _responseDestination, customPayload: _customPayload, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function loadTupleJettonTransfer(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _destination = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    const _customPayload = source.readCellOpt();
    const _forwardTonAmount = source.readBigNumber();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransfer' as const, queryId: _queryId, amount: _amount, destination: _destination, responseDestination: _responseDestination, customPayload: _customPayload, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function loadGetterTupleJettonTransfer(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _destination = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    const _customPayload = source.readCellOpt();
    const _forwardTonAmount = source.readBigNumber();
    const _forwardPayload = source.readCell().asSlice();
    return { $$type: 'JettonTransfer' as const, queryId: _queryId, amount: _amount, destination: _destination, responseDestination: _responseDestination, customPayload: _customPayload, forwardTonAmount: _forwardTonAmount, forwardPayload: _forwardPayload };
}

export function storeTupleJettonTransfer(source: JettonTransfer) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeNumber(source.amount);
    builder.writeAddress(source.destination);
    builder.writeAddress(source.responseDestination);
    builder.writeCell(source.customPayload);
    builder.writeNumber(source.forwardTonAmount);
    builder.writeSlice(source.forwardPayload.asCell());
    return builder.build();
}

export function dictValueParserJettonTransfer(): DictionaryValue<JettonTransfer> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonTransfer(src)).endCell());
        },
        parse: (src) => {
            return loadJettonTransfer(src.loadRef().beginParse());
        }
    }
}

export type JettonBurn = {
    $$type: 'JettonBurn';
    queryId: bigint;
    amount: bigint;
    responseDestination: Address | null;
    customPayload: Cell | null;
}

export function storeJettonBurn(src: JettonBurn) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(1499400124, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeCoins(src.amount);
        b_0.storeAddress(src.responseDestination);
        if (src.customPayload !== null && src.customPayload !== undefined) { b_0.storeBit(true).storeRef(src.customPayload); } else { b_0.storeBit(false); }
    };
}

export function loadJettonBurn(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 1499400124) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _amount = sc_0.loadCoins();
    const _responseDestination = sc_0.loadMaybeAddress();
    const _customPayload = sc_0.loadBit() ? sc_0.loadRef() : null;
    return { $$type: 'JettonBurn' as const, queryId: _queryId, amount: _amount, responseDestination: _responseDestination, customPayload: _customPayload };
}

export function loadTupleJettonBurn(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _responseDestination = source.readAddressOpt();
    const _customPayload = source.readCellOpt();
    return { $$type: 'JettonBurn' as const, queryId: _queryId, amount: _amount, responseDestination: _responseDestination, customPayload: _customPayload };
}

export function loadGetterTupleJettonBurn(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _responseDestination = source.readAddressOpt();
    const _customPayload = source.readCellOpt();
    return { $$type: 'JettonBurn' as const, queryId: _queryId, amount: _amount, responseDestination: _responseDestination, customPayload: _customPayload };
}

export function storeTupleJettonBurn(source: JettonBurn) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeNumber(source.amount);
    builder.writeAddress(source.responseDestination);
    builder.writeCell(source.customPayload);
    return builder.build();
}

export function dictValueParserJettonBurn(): DictionaryValue<JettonBurn> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonBurn(src)).endCell());
        },
        parse: (src) => {
            return loadJettonBurn(src.loadRef().beginParse());
        }
    }
}

export type JettonBurnNotification = {
    $$type: 'JettonBurnNotification';
    queryId: bigint;
    amount: bigint;
    sender: Address;
    responseDestination: Address | null;
}

export function storeJettonBurnNotification(src: JettonBurnNotification) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(2078119902, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeCoins(src.amount);
        b_0.storeAddress(src.sender);
        b_0.storeAddress(src.responseDestination);
    };
}

export function loadJettonBurnNotification(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 2078119902) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _amount = sc_0.loadCoins();
    const _sender = sc_0.loadAddress();
    const _responseDestination = sc_0.loadMaybeAddress();
    return { $$type: 'JettonBurnNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination };
}

export function loadTupleJettonBurnNotification(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    return { $$type: 'JettonBurnNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination };
}

export function loadGetterTupleJettonBurnNotification(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _amount = source.readBigNumber();
    const _sender = source.readAddress();
    const _responseDestination = source.readAddressOpt();
    return { $$type: 'JettonBurnNotification' as const, queryId: _queryId, amount: _amount, sender: _sender, responseDestination: _responseDestination };
}

export function storeTupleJettonBurnNotification(source: JettonBurnNotification) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeNumber(source.amount);
    builder.writeAddress(source.sender);
    builder.writeAddress(source.responseDestination);
    return builder.build();
}

export function dictValueParserJettonBurnNotification(): DictionaryValue<JettonBurnNotification> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonBurnNotification(src)).endCell());
        },
        parse: (src) => {
            return loadJettonBurnNotification(src.loadRef().beginParse());
        }
    }
}

export type TokenExcesses = {
    $$type: 'TokenExcesses';
    queryId: bigint;
}

export function storeTokenExcesses(src: TokenExcesses) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(3576854235, 32);
        b_0.storeUint(src.queryId, 64);
    };
}

export function loadTokenExcesses(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 3576854235) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    return { $$type: 'TokenExcesses' as const, queryId: _queryId };
}

export function loadTupleTokenExcesses(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'TokenExcesses' as const, queryId: _queryId };
}

export function loadGetterTupleTokenExcesses(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'TokenExcesses' as const, queryId: _queryId };
}

export function storeTupleTokenExcesses(source: TokenExcesses) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    return builder.build();
}

export function dictValueParserTokenExcesses(): DictionaryValue<TokenExcesses> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeTokenExcesses(src)).endCell());
        },
        parse: (src) => {
            return loadTokenExcesses(src.loadRef().beginParse());
        }
    }
}

export type JettonTransferError = {
    $$type: 'JettonTransferError';
    queryId: bigint;
}

export function storeJettonTransferError(src: JettonTransferError) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(4294967295, 32);
        b_0.storeUint(src.queryId, 64);
    };
}

export function loadJettonTransferError(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 4294967295) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    return { $$type: 'JettonTransferError' as const, queryId: _queryId };
}

export function loadTupleJettonTransferError(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'JettonTransferError' as const, queryId: _queryId };
}

export function loadGetterTupleJettonTransferError(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'JettonTransferError' as const, queryId: _queryId };
}

export function storeTupleJettonTransferError(source: JettonTransferError) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    return builder.build();
}

export function dictValueParserJettonTransferError(): DictionaryValue<JettonTransferError> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonTransferError(src)).endCell());
        },
        parse: (src) => {
            return loadJettonTransferError(src.loadRef().beginParse());
        }
    }
}

export type JettonData = {
    $$type: 'JettonData';
    totalSupply: bigint;
    mintable: boolean;
    adminAddress: Address;
    jettonContent: Cell;
    jettonWalletCode: Cell;
}

export function storeJettonData(src: JettonData) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeCoins(src.totalSupply);
        b_0.storeBit(src.mintable);
        b_0.storeAddress(src.adminAddress);
        b_0.storeRef(src.jettonContent);
        b_0.storeRef(src.jettonWalletCode);
    };
}

export function loadJettonData(slice: Slice) {
    const sc_0 = slice;
    const _totalSupply = sc_0.loadCoins();
    const _mintable = sc_0.loadBit();
    const _adminAddress = sc_0.loadAddress();
    const _jettonContent = sc_0.loadRef();
    const _jettonWalletCode = sc_0.loadRef();
    return { $$type: 'JettonData' as const, totalSupply: _totalSupply, mintable: _mintable, adminAddress: _adminAddress, jettonContent: _jettonContent, jettonWalletCode: _jettonWalletCode };
}

export function loadTupleJettonData(source: TupleReader) {
    const _totalSupply = source.readBigNumber();
    const _mintable = source.readBoolean();
    const _adminAddress = source.readAddress();
    const _jettonContent = source.readCell();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'JettonData' as const, totalSupply: _totalSupply, mintable: _mintable, adminAddress: _adminAddress, jettonContent: _jettonContent, jettonWalletCode: _jettonWalletCode };
}

export function loadGetterTupleJettonData(source: TupleReader) {
    const _totalSupply = source.readBigNumber();
    const _mintable = source.readBoolean();
    const _adminAddress = source.readAddress();
    const _jettonContent = source.readCell();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'JettonData' as const, totalSupply: _totalSupply, mintable: _mintable, adminAddress: _adminAddress, jettonContent: _jettonContent, jettonWalletCode: _jettonWalletCode };
}

export function storeTupleJettonData(source: JettonData) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.totalSupply);
    builder.writeBoolean(source.mintable);
    builder.writeAddress(source.adminAddress);
    builder.writeCell(source.jettonContent);
    builder.writeCell(source.jettonWalletCode);
    return builder.build();
}

export function dictValueParserJettonData(): DictionaryValue<JettonData> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeJettonData(src)).endCell());
        },
        parse: (src) => {
            return loadJettonData(src.loadRef().beginParse());
        }
    }
}

export type WalletData = {
    $$type: 'WalletData';
    balance: bigint;
    owner: Address;
    minter: Address;
    jettonWalletCode: Cell;
}

export function storeWalletData(src: WalletData) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeCoins(src.balance);
        b_0.storeAddress(src.owner);
        b_0.storeAddress(src.minter);
        b_0.storeRef(src.jettonWalletCode);
    };
}

export function loadWalletData(slice: Slice) {
    const sc_0 = slice;
    const _balance = sc_0.loadCoins();
    const _owner = sc_0.loadAddress();
    const _minter = sc_0.loadAddress();
    const _jettonWalletCode = sc_0.loadRef();
    return { $$type: 'WalletData' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function loadTupleWalletData(source: TupleReader) {
    const _balance = source.readBigNumber();
    const _owner = source.readAddress();
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'WalletData' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function loadGetterTupleWalletData(source: TupleReader) {
    const _balance = source.readBigNumber();
    const _owner = source.readAddress();
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'WalletData' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function storeTupleWalletData(source: WalletData) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.balance);
    builder.writeAddress(source.owner);
    builder.writeAddress(source.minter);
    builder.writeCell(source.jettonWalletCode);
    return builder.build();
}

export function dictValueParserWalletData(): DictionaryValue<WalletData> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeWalletData(src)).endCell());
        },
        parse: (src) => {
            return loadWalletData(src.loadRef().beginParse());
        }
    }
}

export type Mint = {
    $$type: 'Mint';
    queryId: bigint;
    receiver: Address;
    amount: bigint;
}

export function storeMint(src: Mint) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(4096, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeAddress(src.receiver);
        b_0.storeCoins(src.amount);
    };
}

export function loadMint(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 4096) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _receiver = sc_0.loadAddress();
    const _amount = sc_0.loadCoins();
    return { $$type: 'Mint' as const, queryId: _queryId, receiver: _receiver, amount: _amount };
}

export function loadTupleMint(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _receiver = source.readAddress();
    const _amount = source.readBigNumber();
    return { $$type: 'Mint' as const, queryId: _queryId, receiver: _receiver, amount: _amount };
}

export function loadGetterTupleMint(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _receiver = source.readAddress();
    const _amount = source.readBigNumber();
    return { $$type: 'Mint' as const, queryId: _queryId, receiver: _receiver, amount: _amount };
}

export function storeTupleMint(source: Mint) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeAddress(source.receiver);
    builder.writeNumber(source.amount);
    return builder.build();
}

export function dictValueParserMint(): DictionaryValue<Mint> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeMint(src)).endCell());
        },
        parse: (src) => {
            return loadMint(src.loadRef().beginParse());
        }
    }
}

export type ChangeAdmin = {
    $$type: 'ChangeAdmin';
    newAdmin: Address;
}

export function storeChangeAdmin(src: ChangeAdmin) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(4097, 32);
        b_0.storeAddress(src.newAdmin);
    };
}

export function loadChangeAdmin(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 4097) { throw Error('Invalid prefix'); }
    const _newAdmin = sc_0.loadAddress();
    return { $$type: 'ChangeAdmin' as const, newAdmin: _newAdmin };
}

export function loadTupleChangeAdmin(source: TupleReader) {
    const _newAdmin = source.readAddress();
    return { $$type: 'ChangeAdmin' as const, newAdmin: _newAdmin };
}

export function loadGetterTupleChangeAdmin(source: TupleReader) {
    const _newAdmin = source.readAddress();
    return { $$type: 'ChangeAdmin' as const, newAdmin: _newAdmin };
}

export function storeTupleChangeAdmin(source: ChangeAdmin) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.newAdmin);
    return builder.build();
}

export function dictValueParserChangeAdmin(): DictionaryValue<ChangeAdmin> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeChangeAdmin(src)).endCell());
        },
        parse: (src) => {
            return loadChangeAdmin(src.loadRef().beginParse());
        }
    }
}

export type ClaimData = {
    $$type: 'ClaimData';
    user: Address;
    amount: bigint;
    referenceId: bigint;
    deadline: bigint;
}

export function storeClaimData(src: ClaimData) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.user);
        b_0.storeCoins(src.amount);
        b_0.storeUint(src.referenceId, 256);
        b_0.storeUint(src.deadline, 64);
    };
}

export function loadClaimData(slice: Slice) {
    const sc_0 = slice;
    const _user = sc_0.loadAddress();
    const _amount = sc_0.loadCoins();
    const _referenceId = sc_0.loadUintBig(256);
    const _deadline = sc_0.loadUintBig(64);
    return { $$type: 'ClaimData' as const, user: _user, amount: _amount, referenceId: _referenceId, deadline: _deadline };
}

export function loadTupleClaimData(source: TupleReader) {
    const _user = source.readAddress();
    const _amount = source.readBigNumber();
    const _referenceId = source.readBigNumber();
    const _deadline = source.readBigNumber();
    return { $$type: 'ClaimData' as const, user: _user, amount: _amount, referenceId: _referenceId, deadline: _deadline };
}

export function loadGetterTupleClaimData(source: TupleReader) {
    const _user = source.readAddress();
    const _amount = source.readBigNumber();
    const _referenceId = source.readBigNumber();
    const _deadline = source.readBigNumber();
    return { $$type: 'ClaimData' as const, user: _user, amount: _amount, referenceId: _referenceId, deadline: _deadline };
}

export function storeTupleClaimData(source: ClaimData) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.user);
    builder.writeNumber(source.amount);
    builder.writeNumber(source.referenceId);
    builder.writeNumber(source.deadline);
    return builder.build();
}

export function dictValueParserClaimData(): DictionaryValue<ClaimData> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeClaimData(src)).endCell());
        },
        parse: (src) => {
            return loadClaimData(src.loadRef().beginParse());
        }
    }
}

export type Claim = {
    $$type: 'Claim';
    queryId: bigint;
    data: Cell;
    signature: Slice;
}

export function storeClaim(src: Claim) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(8192, 32);
        b_0.storeUint(src.queryId, 64);
        b_0.storeRef(src.data);
        b_0.storeBuilder(src.signature.asBuilder());
    };
}

export function loadClaim(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 8192) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    const _data = sc_0.loadRef();
    const _signature = sc_0;
    return { $$type: 'Claim' as const, queryId: _queryId, data: _data, signature: _signature };
}

export function loadTupleClaim(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _data = source.readCell();
    const _signature = source.readCell().asSlice();
    return { $$type: 'Claim' as const, queryId: _queryId, data: _data, signature: _signature };
}

export function loadGetterTupleClaim(source: TupleReader) {
    const _queryId = source.readBigNumber();
    const _data = source.readCell();
    const _signature = source.readCell().asSlice();
    return { $$type: 'Claim' as const, queryId: _queryId, data: _data, signature: _signature };
}

export function storeTupleClaim(source: Claim) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    builder.writeCell(source.data);
    builder.writeSlice(source.signature.asCell());
    return builder.build();
}

export function dictValueParserClaim(): DictionaryValue<Claim> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeClaim(src)).endCell());
        },
        parse: (src) => {
            return loadClaim(src.loadRef().beginParse());
        }
    }
}

export type RotateSigner = {
    $$type: 'RotateSigner';
    newSigner: bigint;
}

export function storeRotateSigner(src: RotateSigner) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(8193, 32);
        b_0.storeUint(src.newSigner, 256);
    };
}

export function loadRotateSigner(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 8193) { throw Error('Invalid prefix'); }
    const _newSigner = sc_0.loadUintBig(256);
    return { $$type: 'RotateSigner' as const, newSigner: _newSigner };
}

export function loadTupleRotateSigner(source: TupleReader) {
    const _newSigner = source.readBigNumber();
    return { $$type: 'RotateSigner' as const, newSigner: _newSigner };
}

export function loadGetterTupleRotateSigner(source: TupleReader) {
    const _newSigner = source.readBigNumber();
    return { $$type: 'RotateSigner' as const, newSigner: _newSigner };
}

export function storeTupleRotateSigner(source: RotateSigner) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.newSigner);
    return builder.build();
}

export function dictValueParserRotateSigner(): DictionaryValue<RotateSigner> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeRotateSigner(src)).endCell());
        },
        parse: (src) => {
            return loadRotateSigner(src.loadRef().beginParse());
        }
    }
}

export type SetPaused = {
    $$type: 'SetPaused';
    paused: boolean;
}

export function storeSetPaused(src: SetPaused) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(8194, 32);
        b_0.storeBit(src.paused);
    };
}

export function loadSetPaused(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 8194) { throw Error('Invalid prefix'); }
    const _paused = sc_0.loadBit();
    return { $$type: 'SetPaused' as const, paused: _paused };
}

export function loadTupleSetPaused(source: TupleReader) {
    const _paused = source.readBoolean();
    return { $$type: 'SetPaused' as const, paused: _paused };
}

export function loadGetterTupleSetPaused(source: TupleReader) {
    const _paused = source.readBoolean();
    return { $$type: 'SetPaused' as const, paused: _paused };
}

export function storeTupleSetPaused(source: SetPaused) {
    const builder = new TupleBuilder();
    builder.writeBoolean(source.paused);
    return builder.build();
}

export function dictValueParserSetPaused(): DictionaryValue<SetPaused> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeSetPaused(src)).endCell());
        },
        parse: (src) => {
            return loadSetPaused(src.loadRef().beginParse());
        }
    }
}

export type SetDistributor = {
    $$type: 'SetDistributor';
    distributor: Address;
}

export function storeSetDistributor(src: SetDistributor) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(8195, 32);
        b_0.storeAddress(src.distributor);
    };
}

export function loadSetDistributor(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 8195) { throw Error('Invalid prefix'); }
    const _distributor = sc_0.loadAddress();
    return { $$type: 'SetDistributor' as const, distributor: _distributor };
}

export function loadTupleSetDistributor(source: TupleReader) {
    const _distributor = source.readAddress();
    return { $$type: 'SetDistributor' as const, distributor: _distributor };
}

export function loadGetterTupleSetDistributor(source: TupleReader) {
    const _distributor = source.readAddress();
    return { $$type: 'SetDistributor' as const, distributor: _distributor };
}

export function storeTupleSetDistributor(source: SetDistributor) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.distributor);
    return builder.build();
}

export function dictValueParserSetDistributor(): DictionaryValue<SetDistributor> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeSetDistributor(src)).endCell());
        },
        parse: (src) => {
            return loadSetDistributor(src.loadRef().beginParse());
        }
    }
}

export type Release = {
    $$type: 'Release';
    queryId: bigint;
}

export function storeRelease(src: Release) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(12289, 32);
        b_0.storeUint(src.queryId, 64);
    };
}

export function loadRelease(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 12289) { throw Error('Invalid prefix'); }
    const _queryId = sc_0.loadUintBig(64);
    return { $$type: 'Release' as const, queryId: _queryId };
}

export function loadTupleRelease(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'Release' as const, queryId: _queryId };
}

export function loadGetterTupleRelease(source: TupleReader) {
    const _queryId = source.readBigNumber();
    return { $$type: 'Release' as const, queryId: _queryId };
}

export function storeTupleRelease(source: Release) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.queryId);
    return builder.build();
}

export function dictValueParserRelease(): DictionaryValue<Release> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeRelease(src)).endCell());
        },
        parse: (src) => {
            return loadRelease(src.loadRef().beginParse());
        }
    }
}

export type XeraJettonWallet$Data = {
    $$type: 'XeraJettonWallet$Data';
    balance: bigint;
    owner: Address;
    minter: Address;
    jettonWalletCode: Cell;
}

export function storeXeraJettonWallet$Data(src: XeraJettonWallet$Data) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeCoins(src.balance);
        b_0.storeAddress(src.owner);
        b_0.storeAddress(src.minter);
        b_0.storeRef(src.jettonWalletCode);
    };
}

export function loadXeraJettonWallet$Data(slice: Slice) {
    const sc_0 = slice;
    const _balance = sc_0.loadCoins();
    const _owner = sc_0.loadAddress();
    const _minter = sc_0.loadAddress();
    const _jettonWalletCode = sc_0.loadRef();
    return { $$type: 'XeraJettonWallet$Data' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function loadTupleXeraJettonWallet$Data(source: TupleReader) {
    const _balance = source.readBigNumber();
    const _owner = source.readAddress();
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'XeraJettonWallet$Data' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function loadGetterTupleXeraJettonWallet$Data(source: TupleReader) {
    const _balance = source.readBigNumber();
    const _owner = source.readAddress();
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    return { $$type: 'XeraJettonWallet$Data' as const, balance: _balance, owner: _owner, minter: _minter, jettonWalletCode: _jettonWalletCode };
}

export function storeTupleXeraJettonWallet$Data(source: XeraJettonWallet$Data) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.balance);
    builder.writeAddress(source.owner);
    builder.writeAddress(source.minter);
    builder.writeCell(source.jettonWalletCode);
    return builder.build();
}

export function dictValueParserXeraJettonWallet$Data(): DictionaryValue<XeraJettonWallet$Data> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeXeraJettonWallet$Data(src)).endCell());
        },
        parse: (src) => {
            return loadXeraJettonWallet$Data(src.loadRef().beginParse());
        }
    }
}

export type XeraMiningDistributor$Data = {
    $$type: 'XeraMiningDistributor$Data';
    minter: Address;
    jettonWalletCode: Cell;
    vesting: Address;
    signerPublicKey: bigint;
    admin: Address;
    maxAllocation: bigint;
    totalDistributed: bigint;
    paused: boolean;
    consumed: Dictionary<bigint, boolean>;
}

export function storeXeraMiningDistributor$Data(src: XeraMiningDistributor$Data) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.minter);
        b_0.storeRef(src.jettonWalletCode);
        b_0.storeAddress(src.vesting);
        b_0.storeUint(src.signerPublicKey, 256);
        const b_1 = new Builder();
        b_1.storeAddress(src.admin);
        b_1.storeCoins(src.maxAllocation);
        b_1.storeCoins(src.totalDistributed);
        b_1.storeBit(src.paused);
        b_1.storeDict(src.consumed, Dictionary.Keys.BigInt(257), Dictionary.Values.Bool());
        b_0.storeRef(b_1.endCell());
    };
}

export function loadXeraMiningDistributor$Data(slice: Slice) {
    const sc_0 = slice;
    const _minter = sc_0.loadAddress();
    const _jettonWalletCode = sc_0.loadRef();
    const _vesting = sc_0.loadAddress();
    const _signerPublicKey = sc_0.loadUintBig(256);
    const sc_1 = sc_0.loadRef().beginParse();
    const _admin = sc_1.loadAddress();
    const _maxAllocation = sc_1.loadCoins();
    const _totalDistributed = sc_1.loadCoins();
    const _paused = sc_1.loadBit();
    const _consumed = Dictionary.load(Dictionary.Keys.BigInt(257), Dictionary.Values.Bool(), sc_1);
    return { $$type: 'XeraMiningDistributor$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, vesting: _vesting, signerPublicKey: _signerPublicKey, admin: _admin, maxAllocation: _maxAllocation, totalDistributed: _totalDistributed, paused: _paused, consumed: _consumed };
}

export function loadTupleXeraMiningDistributor$Data(source: TupleReader) {
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    const _vesting = source.readAddress();
    const _signerPublicKey = source.readBigNumber();
    const _admin = source.readAddress();
    const _maxAllocation = source.readBigNumber();
    const _totalDistributed = source.readBigNumber();
    const _paused = source.readBoolean();
    const _consumed = Dictionary.loadDirect(Dictionary.Keys.BigInt(257), Dictionary.Values.Bool(), source.readCellOpt());
    return { $$type: 'XeraMiningDistributor$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, vesting: _vesting, signerPublicKey: _signerPublicKey, admin: _admin, maxAllocation: _maxAllocation, totalDistributed: _totalDistributed, paused: _paused, consumed: _consumed };
}

export function loadGetterTupleXeraMiningDistributor$Data(source: TupleReader) {
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    const _vesting = source.readAddress();
    const _signerPublicKey = source.readBigNumber();
    const _admin = source.readAddress();
    const _maxAllocation = source.readBigNumber();
    const _totalDistributed = source.readBigNumber();
    const _paused = source.readBoolean();
    const _consumed = Dictionary.loadDirect(Dictionary.Keys.BigInt(257), Dictionary.Values.Bool(), source.readCellOpt());
    return { $$type: 'XeraMiningDistributor$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, vesting: _vesting, signerPublicKey: _signerPublicKey, admin: _admin, maxAllocation: _maxAllocation, totalDistributed: _totalDistributed, paused: _paused, consumed: _consumed };
}

export function storeTupleXeraMiningDistributor$Data(source: XeraMiningDistributor$Data) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.minter);
    builder.writeCell(source.jettonWalletCode);
    builder.writeAddress(source.vesting);
    builder.writeNumber(source.signerPublicKey);
    builder.writeAddress(source.admin);
    builder.writeNumber(source.maxAllocation);
    builder.writeNumber(source.totalDistributed);
    builder.writeBoolean(source.paused);
    builder.writeCell(source.consumed.size > 0 ? beginCell().storeDictDirect(source.consumed, Dictionary.Keys.BigInt(257), Dictionary.Values.Bool()).endCell() : null);
    return builder.build();
}

export function dictValueParserXeraMiningDistributor$Data(): DictionaryValue<XeraMiningDistributor$Data> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeXeraMiningDistributor$Data(src)).endCell());
        },
        parse: (src) => {
            return loadXeraMiningDistributor$Data(src.loadRef().beginParse());
        }
    }
}

 type XeraJettonWallet_init_args = {
    $$type: 'XeraJettonWallet_init_args';
    minter: Address;
    owner: Address;
    jettonWalletCode: Cell;
}

function initXeraJettonWallet_init_args(src: XeraJettonWallet_init_args) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.minter);
        b_0.storeAddress(src.owner);
        b_0.storeRef(src.jettonWalletCode);
    };
}

async function XeraJettonWallet_init(minter: Address, owner: Address, jettonWalletCode: Cell) {
    const __code = Cell.fromHex('b5ee9c7241020f010003ec000228ff008e88f4a413f4bcf2c80bed5320e303ed43d901030151a65ec0bb513434800066fe803e903e9035154c1b05277e903e9035154800f4561c140cf8b6cf1b11200200085473212301f63001d072d721d200d200fa4021103450666f04f86102f862ed44d0d200019bfa00fa40fa40d455306c149dfa40fa40d4552003d158705033e2058e3a038020d7217021d749c21f9430d31f01de8210178d4519ba8e1dd33ffa00596c2112a05023c87f01ca0055305043fa02ce12ceccc9ed54e05f05e003d70d1f0404f0f2e082218210178d4519ba8fe231d33ffa00fa40d72c01916d93fa4001e201fa00f8416f2410235f0381740b531ac70592317f8e8f104910384abb25db3c4ab010491038e2f2f45174a021c2009437135f03e30d206eb3915be30d4003c87f01ca0055305043fa02ce12ceccc9ed54e02182100f8a7ea5ba050607080168546331db3c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d0c7050900b27170274713506ac8553082107362d09c5005cb1f13cb3f01fa02cecec9264314450010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb0000a6206ef2d0807083067004c8018210d53276db58cb1fcb3fc91034413010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb0004fc8f6f31d33ffa00fa40d72c01916d93fa4001e201f40431fa00f8416f245b8142ac3228c705f2f48166805385bef2f45174a152842adb3c5c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d050767080407f2b4813507dc8e0018210595f07bcbae3025f05090a0b0e001ef82ac87001ca0055215023cececcc900f255508210178d45195007cb1f15cb3f5003fa02ce01206e9430cf84809201cee201fa02cec910561058103441301810464515504403c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb004003c87f01ca0055305043fa02ce12ceccc9ed5402fed33ffa00d72c01916d93fa4001e231f8416f245b8142ac3225c705f2f48166805352bef2f45141a17080405414357f08c8553082107bdd97de5005cb1f13cb3f01fa02ce01206e9430cf84809201cee2c926044313506610246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf818ae2f400c9010c0d001a58cf8680cf8480f400f400cf81002cfb004003c87f01ca0055305043fa02ce12ceccc9ed540006f2c08210f9a805');
    const builder = beginCell();
    builder.storeUint(0, 1);
    initXeraJettonWallet_init_args({ $$type: 'XeraJettonWallet_init_args', minter, owner, jettonWalletCode })(builder);
    const __data = builder.endCell();
    return { code: __code, data: __data };
}

export const XeraJettonWallet_errors = {
    2: { message: "Stack underflow" },
    3: { message: "Stack overflow" },
    4: { message: "Integer overflow" },
    5: { message: "Integer out of expected range" },
    6: { message: "Invalid opcode" },
    7: { message: "Type check error" },
    8: { message: "Cell overflow" },
    9: { message: "Cell underflow" },
    10: { message: "Dictionary error" },
    11: { message: "'Unknown' error" },
    12: { message: "Fatal error" },
    13: { message: "Out of gas error" },
    14: { message: "Virtualization error" },
    32: { message: "Action list is invalid" },
    33: { message: "Action list is too long" },
    34: { message: "Action is invalid or not supported" },
    35: { message: "Invalid source address in outbound message" },
    36: { message: "Invalid destination address in outbound message" },
    37: { message: "Not enough Toncoin" },
    38: { message: "Not enough extra currencies" },
    39: { message: "Outbound message does not fit into a cell after rewriting" },
    40: { message: "Cannot process a message" },
    41: { message: "Library reference is null" },
    42: { message: "Library change action error" },
    43: { message: "Exceeded maximum number of cells in the library or the maximum depth of the Merkle tree" },
    50: { message: "Account state size exceeded limits" },
    128: { message: "Null reference exception" },
    129: { message: "Invalid serialization prefix" },
    130: { message: "Invalid incoming message" },
    131: { message: "Constraints error" },
    132: { message: "Access denied" },
    133: { message: "Contract stopped" },
    134: { message: "Invalid argument" },
    135: { message: "Code of a contract was not found" },
    136: { message: "Invalid standard address" },
    138: { message: "Not a basechain address" },
    15577: { message: "XeraMiningDistributor: zero amount" },
    17068: { message: "XeraJettonWallet: not owner" },
    23160: { message: "XeraMiningDistributor: claim expired" },
    26240: { message: "XeraJettonWallet: insufficient balance" },
    29707: { message: "XeraJettonWallet: unauthorized credit" },
    31814: { message: "XeraMiningDistributor: reference already consumed" },
    51332: { message: "XeraMiningDistributor: paused" },
    54449: { message: "XeraMiningDistributor: invalid signature" },
    56540: { message: "XeraMiningDistributor: not admin" },
    61156: { message: "XeraMiningDistributor: mining cap exceeded" },
    63486: { message: "XeraMiningDistributor: insufficient gas attached" },
} as const

export const XeraJettonWallet_errors_backward = {
    "Stack underflow": 2,
    "Stack overflow": 3,
    "Integer overflow": 4,
    "Integer out of expected range": 5,
    "Invalid opcode": 6,
    "Type check error": 7,
    "Cell overflow": 8,
    "Cell underflow": 9,
    "Dictionary error": 10,
    "'Unknown' error": 11,
    "Fatal error": 12,
    "Out of gas error": 13,
    "Virtualization error": 14,
    "Action list is invalid": 32,
    "Action list is too long": 33,
    "Action is invalid or not supported": 34,
    "Invalid source address in outbound message": 35,
    "Invalid destination address in outbound message": 36,
    "Not enough Toncoin": 37,
    "Not enough extra currencies": 38,
    "Outbound message does not fit into a cell after rewriting": 39,
    "Cannot process a message": 40,
    "Library reference is null": 41,
    "Library change action error": 42,
    "Exceeded maximum number of cells in the library or the maximum depth of the Merkle tree": 43,
    "Account state size exceeded limits": 50,
    "Null reference exception": 128,
    "Invalid serialization prefix": 129,
    "Invalid incoming message": 130,
    "Constraints error": 131,
    "Access denied": 132,
    "Contract stopped": 133,
    "Invalid argument": 134,
    "Code of a contract was not found": 135,
    "Invalid standard address": 136,
    "Not a basechain address": 138,
    "XeraMiningDistributor: zero amount": 15577,
    "XeraJettonWallet: not owner": 17068,
    "XeraMiningDistributor: claim expired": 23160,
    "XeraJettonWallet: insufficient balance": 26240,
    "XeraJettonWallet: unauthorized credit": 29707,
    "XeraMiningDistributor: reference already consumed": 31814,
    "XeraMiningDistributor: paused": 51332,
    "XeraMiningDistributor: invalid signature": 54449,
    "XeraMiningDistributor: not admin": 56540,
    "XeraMiningDistributor: mining cap exceeded": 61156,
    "XeraMiningDistributor: insufficient gas attached": 63486,
} as const

const XeraJettonWallet_types: ABIType[] = [
    {"name":"DataSize","header":null,"fields":[{"name":"cells","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"bits","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"refs","type":{"kind":"simple","type":"int","optional":false,"format":257}}]},
    {"name":"SignedBundle","header":null,"fields":[{"name":"signature","type":{"kind":"simple","type":"fixed-bytes","optional":false,"format":64}},{"name":"signedData","type":{"kind":"simple","type":"slice","optional":false,"format":"remainder"}}]},
    {"name":"StateInit","header":null,"fields":[{"name":"code","type":{"kind":"simple","type":"cell","optional":false}},{"name":"data","type":{"kind":"simple","type":"cell","optional":false}}]},
    {"name":"Context","header":null,"fields":[{"name":"bounceable","type":{"kind":"simple","type":"bool","optional":false}},{"name":"sender","type":{"kind":"simple","type":"address","optional":false}},{"name":"value","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"raw","type":{"kind":"simple","type":"slice","optional":false}}]},
    {"name":"SendParameters","header":null,"fields":[{"name":"mode","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"body","type":{"kind":"simple","type":"cell","optional":true}},{"name":"code","type":{"kind":"simple","type":"cell","optional":true}},{"name":"data","type":{"kind":"simple","type":"cell","optional":true}},{"name":"value","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"to","type":{"kind":"simple","type":"address","optional":false}},{"name":"bounce","type":{"kind":"simple","type":"bool","optional":false}}]},
    {"name":"MessageParameters","header":null,"fields":[{"name":"mode","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"body","type":{"kind":"simple","type":"cell","optional":true}},{"name":"value","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"to","type":{"kind":"simple","type":"address","optional":false}},{"name":"bounce","type":{"kind":"simple","type":"bool","optional":false}}]},
    {"name":"DeployParameters","header":null,"fields":[{"name":"mode","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"body","type":{"kind":"simple","type":"cell","optional":true}},{"name":"value","type":{"kind":"simple","type":"int","optional":false,"format":257}},{"name":"bounce","type":{"kind":"simple","type":"bool","optional":false}},{"name":"init","type":{"kind":"simple","type":"StateInit","optional":false}}]},
    {"name":"StdAddress","header":null,"fields":[{"name":"workchain","type":{"kind":"simple","type":"int","optional":false,"format":8}},{"name":"address","type":{"kind":"simple","type":"uint","optional":false,"format":256}}]},
    {"name":"VarAddress","header":null,"fields":[{"name":"workchain","type":{"kind":"simple","type":"int","optional":false,"format":32}},{"name":"address","type":{"kind":"simple","type":"slice","optional":false}}]},
    {"name":"BasechainAddress","header":null,"fields":[{"name":"hash","type":{"kind":"simple","type":"int","optional":true,"format":257}}]},
    {"name":"Deploy","header":2490013878,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"DeployOk","header":2952335191,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"FactoryDeploy","header":1829761339,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"cashback","type":{"kind":"simple","type":"address","optional":false}}]},
    {"name":"JettonTransferInternal","header":395134233,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"sender","type":{"kind":"simple","type":"address","optional":false}},{"name":"responseDestination","type":{"kind":"simple","type":"address","optional":true}},{"name":"forwardTonAmount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"forwardPayload","type":{"kind":"simple","type":"slice","optional":false,"format":"remainder"}}]},
    {"name":"JettonTransferNotification","header":1935855772,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"sender","type":{"kind":"simple","type":"address","optional":false}},{"name":"forwardPayload","type":{"kind":"simple","type":"slice","optional":false,"format":"remainder"}}]},
    {"name":"JettonTransfer","header":260734629,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"destination","type":{"kind":"simple","type":"address","optional":false}},{"name":"responseDestination","type":{"kind":"simple","type":"address","optional":true}},{"name":"customPayload","type":{"kind":"simple","type":"cell","optional":true}},{"name":"forwardTonAmount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"forwardPayload","type":{"kind":"simple","type":"slice","optional":false,"format":"remainder"}}]},
    {"name":"JettonBurn","header":1499400124,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"responseDestination","type":{"kind":"simple","type":"address","optional":true}},{"name":"customPayload","type":{"kind":"simple","type":"cell","optional":true}}]},
    {"name":"JettonBurnNotification","header":2078119902,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"sender","type":{"kind":"simple","type":"address","optional":false}},{"name":"responseDestination","type":{"kind":"simple","type":"address","optional":true}}]},
    {"name":"TokenExcesses","header":3576854235,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"JettonTransferError","header":4294967295,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"JettonData","header":null,"fields":[{"name":"totalSupply","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"mintable","type":{"kind":"simple","type":"bool","optional":false}},{"name":"adminAddress","type":{"kind":"simple","type":"address","optional":false}},{"name":"jettonContent","type":{"kind":"simple","type":"cell","optional":false}},{"name":"jettonWalletCode","type":{"kind":"simple","type":"cell","optional":false}}]},
    {"name":"WalletData","header":null,"fields":[{"name":"balance","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"owner","type":{"kind":"simple","type":"address","optional":false}},{"name":"minter","type":{"kind":"simple","type":"address","optional":false}},{"name":"jettonWalletCode","type":{"kind":"simple","type":"cell","optional":false}}]},
    {"name":"Mint","header":4096,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"receiver","type":{"kind":"simple","type":"address","optional":false}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}}]},
    {"name":"ChangeAdmin","header":4097,"fields":[{"name":"newAdmin","type":{"kind":"simple","type":"address","optional":false}}]},
    {"name":"ClaimData","header":null,"fields":[{"name":"user","type":{"kind":"simple","type":"address","optional":false}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"referenceId","type":{"kind":"simple","type":"uint","optional":false,"format":256}},{"name":"deadline","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"Claim","header":8192,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"data","type":{"kind":"simple","type":"cell","optional":false}},{"name":"signature","type":{"kind":"simple","type":"slice","optional":false,"format":"remainder"}}]},
    {"name":"RotateSigner","header":8193,"fields":[{"name":"newSigner","type":{"kind":"simple","type":"uint","optional":false,"format":256}}]},
    {"name":"SetPaused","header":8194,"fields":[{"name":"paused","type":{"kind":"simple","type":"bool","optional":false}}]},
    {"name":"SetDistributor","header":8195,"fields":[{"name":"distributor","type":{"kind":"simple","type":"address","optional":false}}]},
    {"name":"Release","header":12289,"fields":[{"name":"queryId","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"XeraJettonWallet$Data","header":null,"fields":[{"name":"balance","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"owner","type":{"kind":"simple","type":"address","optional":false}},{"name":"minter","type":{"kind":"simple","type":"address","optional":false}},{"name":"jettonWalletCode","type":{"kind":"simple","type":"cell","optional":false}}]},
    {"name":"XeraMiningDistributor$Data","header":null,"fields":[{"name":"minter","type":{"kind":"simple","type":"address","optional":false}},{"name":"jettonWalletCode","type":{"kind":"simple","type":"cell","optional":false}},{"name":"vesting","type":{"kind":"simple","type":"address","optional":false}},{"name":"signerPublicKey","type":{"kind":"simple","type":"uint","optional":false,"format":256}},{"name":"admin","type":{"kind":"simple","type":"address","optional":false}},{"name":"maxAllocation","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"totalDistributed","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"paused","type":{"kind":"simple","type":"bool","optional":false}},{"name":"consumed","type":{"kind":"dict","key":"int","value":"bool"}}]},
]

const XeraJettonWallet_opcodes = {
    "Deploy": 2490013878,
    "DeployOk": 2952335191,
    "FactoryDeploy": 1829761339,
    "JettonTransferInternal": 395134233,
    "JettonTransferNotification": 1935855772,
    "JettonTransfer": 260734629,
    "JettonBurn": 1499400124,
    "JettonBurnNotification": 2078119902,
    "TokenExcesses": 3576854235,
    "JettonTransferError": 4294967295,
    "Mint": 4096,
    "ChangeAdmin": 4097,
    "Claim": 8192,
    "RotateSigner": 8193,
    "SetPaused": 8194,
    "SetDistributor": 8195,
    "Release": 12289,
}

const XeraJettonWallet_getters: ABIGetter[] = [
    {"name":"get_wallet_data","methodId":97026,"arguments":[],"returnType":{"kind":"simple","type":"WalletData","optional":false}},
]

export const XeraJettonWallet_getterMapping: { [key: string]: string } = {
    'get_wallet_data': 'getGetWalletData',
}

const XeraJettonWallet_receivers: ABIReceiver[] = [
    {"receiver":"internal","message":{"kind":"typed","type":"JettonTransferInternal"}},
    {"receiver":"internal","message":{"kind":"typed","type":"JettonTransfer"}},
    {"receiver":"internal","message":{"kind":"typed","type":"JettonBurn"}},
]


export class XeraJettonWallet implements Contract {
    
    public static readonly storageReserve = 0n;
    public static readonly errors = XeraJettonWallet_errors_backward;
    public static readonly opcodes = XeraJettonWallet_opcodes;
    
    static async init(minter: Address, owner: Address, jettonWalletCode: Cell) {
        return await XeraJettonWallet_init(minter, owner, jettonWalletCode);
    }
    
    static async fromInit(minter: Address, owner: Address, jettonWalletCode: Cell) {
        const __gen_init = await XeraJettonWallet_init(minter, owner, jettonWalletCode);
        const address = contractAddress(0, __gen_init);
        return new XeraJettonWallet(address, __gen_init);
    }
    
    static fromAddress(address: Address) {
        return new XeraJettonWallet(address);
    }
    
    readonly address: Address; 
    readonly init?: { code: Cell, data: Cell };
    readonly abi: ContractABI = {
        types:  XeraJettonWallet_types,
        getters: XeraJettonWallet_getters,
        receivers: XeraJettonWallet_receivers,
        errors: XeraJettonWallet_errors,
    };
    
    constructor(address: Address, init?: { code: Cell, data: Cell }) {
        this.address = address;
        this.init = init;
    }
    
    async send(provider: ContractProvider, via: Sender, args: { value: bigint, bounce?: boolean| null | undefined }, message: JettonTransferInternal | JettonTransfer | JettonBurn) {
        
        let body: Cell | null = null;
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'JettonTransferInternal') {
            body = beginCell().store(storeJettonTransferInternal(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'JettonTransfer') {
            body = beginCell().store(storeJettonTransfer(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'JettonBurn') {
            body = beginCell().store(storeJettonBurn(message)).endCell();
        }
        if (body === null) { throw new Error('Invalid message type'); }
        
        await provider.internal(via, { ...args, body: body });
        
    }
    
    async getGetWalletData(provider: ContractProvider) {
        const builder = new TupleBuilder();
        const source = (await provider.get('get_wallet_data', builder.build())).stack;
        const result = loadGetterTupleWalletData(source);
        return result;
    }
    
}