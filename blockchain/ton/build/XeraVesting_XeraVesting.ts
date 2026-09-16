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

export type Tranche = {
    $$type: 'Tranche';
    owner: Address;
    amount: bigint;
    released: bigint;
    start: bigint;
    duration: bigint;
}

export function storeTranche(src: Tranche) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.owner);
        b_0.storeCoins(src.amount);
        b_0.storeCoins(src.released);
        b_0.storeUint(src.start, 64);
        b_0.storeUint(src.duration, 64);
    };
}

export function loadTranche(slice: Slice) {
    const sc_0 = slice;
    const _owner = sc_0.loadAddress();
    const _amount = sc_0.loadCoins();
    const _released = sc_0.loadCoins();
    const _start = sc_0.loadUintBig(64);
    const _duration = sc_0.loadUintBig(64);
    return { $$type: 'Tranche' as const, owner: _owner, amount: _amount, released: _released, start: _start, duration: _duration };
}

export function loadTupleTranche(source: TupleReader) {
    const _owner = source.readAddress();
    const _amount = source.readBigNumber();
    const _released = source.readBigNumber();
    const _start = source.readBigNumber();
    const _duration = source.readBigNumber();
    return { $$type: 'Tranche' as const, owner: _owner, amount: _amount, released: _released, start: _start, duration: _duration };
}

export function loadGetterTupleTranche(source: TupleReader) {
    const _owner = source.readAddress();
    const _amount = source.readBigNumber();
    const _released = source.readBigNumber();
    const _start = source.readBigNumber();
    const _duration = source.readBigNumber();
    return { $$type: 'Tranche' as const, owner: _owner, amount: _amount, released: _released, start: _start, duration: _duration };
}

export function storeTupleTranche(source: Tranche) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.owner);
    builder.writeNumber(source.amount);
    builder.writeNumber(source.released);
    builder.writeNumber(source.start);
    builder.writeNumber(source.duration);
    return builder.build();
}

export function dictValueParserTranche(): DictionaryValue<Tranche> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeTranche(src)).endCell());
        },
        parse: (src) => {
            return loadTranche(src.loadRef().beginParse());
        }
    }
}

export type ReleaseOne = {
    $$type: 'ReleaseOne';
    referenceId: bigint;
}

export function storeReleaseOne(src: ReleaseOne) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeUint(128116498, 32);
        b_0.storeUint(src.referenceId, 256);
    };
}

export function loadReleaseOne(slice: Slice) {
    const sc_0 = slice;
    if (sc_0.loadUint(32) !== 128116498) { throw Error('Invalid prefix'); }
    const _referenceId = sc_0.loadUintBig(256);
    return { $$type: 'ReleaseOne' as const, referenceId: _referenceId };
}

export function loadTupleReleaseOne(source: TupleReader) {
    const _referenceId = source.readBigNumber();
    return { $$type: 'ReleaseOne' as const, referenceId: _referenceId };
}

export function loadGetterTupleReleaseOne(source: TupleReader) {
    const _referenceId = source.readBigNumber();
    return { $$type: 'ReleaseOne' as const, referenceId: _referenceId };
}

export function storeTupleReleaseOne(source: ReleaseOne) {
    const builder = new TupleBuilder();
    builder.writeNumber(source.referenceId);
    return builder.build();
}

export function dictValueParserReleaseOne(): DictionaryValue<ReleaseOne> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeReleaseOne(src)).endCell());
        },
        parse: (src) => {
            return loadReleaseOne(src.loadRef().beginParse());
        }
    }
}

export type XeraVesting$Data = {
    $$type: 'XeraVesting$Data';
    minter: Address;
    jettonWalletCode: Cell;
    distributor: Address;
    admin: Address;
    vestingDuration: bigint;
    paused: boolean;
    tranches: Dictionary<bigint, Tranche>;
    userLockedTotal: Dictionary<Address, bigint>;
}

export function storeXeraVesting$Data(src: XeraVesting$Data) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.minter);
        b_0.storeRef(src.jettonWalletCode);
        b_0.storeAddress(src.distributor);
        b_0.storeAddress(src.admin);
        b_0.storeUint(src.vestingDuration, 64);
        b_0.storeBit(src.paused);
        b_0.storeDict(src.tranches, Dictionary.Keys.BigInt(257), dictValueParserTranche());
        b_0.storeDict(src.userLockedTotal, Dictionary.Keys.Address(), Dictionary.Values.BigInt(257));
    };
}

export function loadXeraVesting$Data(slice: Slice) {
    const sc_0 = slice;
    const _minter = sc_0.loadAddress();
    const _jettonWalletCode = sc_0.loadRef();
    const _distributor = sc_0.loadAddress();
    const _admin = sc_0.loadAddress();
    const _vestingDuration = sc_0.loadUintBig(64);
    const _paused = sc_0.loadBit();
    const _tranches = Dictionary.load(Dictionary.Keys.BigInt(257), dictValueParserTranche(), sc_0);
    const _userLockedTotal = Dictionary.load(Dictionary.Keys.Address(), Dictionary.Values.BigInt(257), sc_0);
    return { $$type: 'XeraVesting$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, distributor: _distributor, admin: _admin, vestingDuration: _vestingDuration, paused: _paused, tranches: _tranches, userLockedTotal: _userLockedTotal };
}

export function loadTupleXeraVesting$Data(source: TupleReader) {
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    const _distributor = source.readAddress();
    const _admin = source.readAddress();
    const _vestingDuration = source.readBigNumber();
    const _paused = source.readBoolean();
    const _tranches = Dictionary.loadDirect(Dictionary.Keys.BigInt(257), dictValueParserTranche(), source.readCellOpt());
    const _userLockedTotal = Dictionary.loadDirect(Dictionary.Keys.Address(), Dictionary.Values.BigInt(257), source.readCellOpt());
    return { $$type: 'XeraVesting$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, distributor: _distributor, admin: _admin, vestingDuration: _vestingDuration, paused: _paused, tranches: _tranches, userLockedTotal: _userLockedTotal };
}

export function loadGetterTupleXeraVesting$Data(source: TupleReader) {
    const _minter = source.readAddress();
    const _jettonWalletCode = source.readCell();
    const _distributor = source.readAddress();
    const _admin = source.readAddress();
    const _vestingDuration = source.readBigNumber();
    const _paused = source.readBoolean();
    const _tranches = Dictionary.loadDirect(Dictionary.Keys.BigInt(257), dictValueParserTranche(), source.readCellOpt());
    const _userLockedTotal = Dictionary.loadDirect(Dictionary.Keys.Address(), Dictionary.Values.BigInt(257), source.readCellOpt());
    return { $$type: 'XeraVesting$Data' as const, minter: _minter, jettonWalletCode: _jettonWalletCode, distributor: _distributor, admin: _admin, vestingDuration: _vestingDuration, paused: _paused, tranches: _tranches, userLockedTotal: _userLockedTotal };
}

export function storeTupleXeraVesting$Data(source: XeraVesting$Data) {
    const builder = new TupleBuilder();
    builder.writeAddress(source.minter);
    builder.writeCell(source.jettonWalletCode);
    builder.writeAddress(source.distributor);
    builder.writeAddress(source.admin);
    builder.writeNumber(source.vestingDuration);
    builder.writeBoolean(source.paused);
    builder.writeCell(source.tranches.size > 0 ? beginCell().storeDictDirect(source.tranches, Dictionary.Keys.BigInt(257), dictValueParserTranche()).endCell() : null);
    builder.writeCell(source.userLockedTotal.size > 0 ? beginCell().storeDictDirect(source.userLockedTotal, Dictionary.Keys.Address(), Dictionary.Values.BigInt(257)).endCell() : null);
    return builder.build();
}

export function dictValueParserXeraVesting$Data(): DictionaryValue<XeraVesting$Data> {
    return {
        serialize: (src, builder) => {
            builder.storeRef(beginCell().store(storeXeraVesting$Data(src)).endCell());
        },
        parse: (src) => {
            return loadXeraVesting$Data(src.loadRef().beginParse());
        }
    }
}

 type XeraVesting_init_args = {
    $$type: 'XeraVesting_init_args';
    minter: Address;
    jettonWalletCode: Cell;
    distributor: Address;
    admin: Address;
    vestingDurationSeconds: bigint;
}

function initXeraVesting_init_args(src: XeraVesting_init_args) {
    return (builder: Builder) => {
        const b_0 = builder;
        b_0.storeAddress(src.minter);
        b_0.storeRef(src.jettonWalletCode);
        b_0.storeAddress(src.distributor);
        b_0.storeAddress(src.admin);
        const b_1 = new Builder();
        b_1.storeInt(src.vestingDurationSeconds, 257);
        b_0.storeRef(b_1.endCell());
    };
}

async function XeraVesting_init(minter: Address, jettonWalletCode: Cell, distributor: Address, admin: Address, vestingDurationSeconds: bigint) {
    const __code = Cell.fromHex('b5ee9c72410225010009e3000228ff008e88f4a413f4bcf2c80bed5320e303ed43d901090202710207020120030501a1b9900ed44d0d200018e21fa40d4fa40fa40d33fd200d401d0f404f404301028102710261025102410236c188e1cfa40d4fa40fa40d401d0810101d700301514433005d155036d6d7059e25507db3c6c818040104db3c0f01cdb9ee4ed44d0d200018e21fa40d4fa40fa40d33fd200d401d0f404f404301028102710261025102410236c188e1cfa40d4fa40fa40d401d0810101d700301514433005d155036d6d7059e25507db3c6c81206e92306d99206ef2d0806f256f05e2206e92306dde806004e810101230259f40d6fa192306ddf206e92306d8e11d0fa40fa00fa00d33fd33f55406c156f05e201a1bcccaf6a268690000c710fd206a7d207d20699fe9006a00e87a027a0218081408138813081288120811b60c470e7d206a7d207d206a00e8408080eb80180a8a219802e8aa81b6b6b82cf12a83ed9e3640c08016c810101230259f40d6fa192306ddf206e92306d8e11d0fa40fa00fa00d33fd33f55406c156f05e2206e923070e0206ef2d0806f25db3c0d02ee3001d072d721d200d200fa4021103450666f04f86102f862ed44d0d200018e21fa40d4fa40fa40d33fd200d401d0f404f404301028102710261025102410236c188e1cfa40d4fa40fa40d401d0810101d700301514433005d155036d6d7059e209925f09e007d70d1ff2e0822182107362d09cbae302210a0c02ee31d33f31fa00fa40f8416f2410235f031069105810471039487a812c5a0cdb3c1cc7051cf2f48200a54c5184c70518f2f4811d1527b3f2f405fa40d3ff308140cf2b8101012359f40d6fa192306ddf206e92306d8e11d0fa40fa00fa00d33fd33f55406c156f05e26ef2f481010170f82324544c302bc8100b01e055405045ce58fa0201fa02cb3fcb3fc9103c12206e953059f45a30944133f415e2104710364540430829db3c81010b0aa049301a810101216e955b59f4593098c801cf004133f441e2105710461035443012c87f01ca0055705078ce15cc13cececb3fca0001c8f40012f400cdc9ed540f03fe821007a2e712ba8f7131d3ff30278101012259f40d6fa192306ddf206e92306d8e11d0fa40fa00fa00d33fd33f55406c156f05e28200f812216eb3f2f4206ef2d0806f2554743253430c11100c10bf10ae109d08111008107f0611110605111205db3c8200854421c200f2f451bba08101012a04103e11101fc8e0218120030d0e23003e34f82301a1547203b9963012a858a9049410246c31e25301bb925b70e001a103ce55405045ce58fa0201fa02cb3fcb3fc9103c4b80206e953059f45a30944133f415e21037465010491038410829db3c81010b511aa152b0810101216e955b59f4593098c801cf004133f441e2db3c7080407f226d6d82089896808b0810460511110504111204c80f1021004481010b22028101014133f40a6fa19401d70030925b6de2206e923070e0206ef2d0800168f828546881db3c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d011011c88c87001ca0055215023cececcc9120228ff008e88f4a413f4bcf2c80bed5320e303ed43d913150151a65ec0bb513434800066fe803e903e9035154c1b05277e903e9035154800f4561c140cf8b6cf1b11201400085473212301f63001d072d721d200d200fa4021103450666f04f86102f862ed44d0d200019bfa00fa40fa40d455306c149dfa40fa40d4552003d158705033e2058e3a038020d7217021d749c21f9430d31f01de8210178d4519ba8e1dd33ffa00596c2112a05023c87f01ca0055305043fa02ce12ceccc9ed54e05f05e003d70d1f1604f0f2e082218210178d4519ba8fe231d33ffa00fa40d72c01916d93fa4001e201fa00f8416f2410235f0381740b531ac70592317f8e8f104910384abb25db3c4ab010491038e2f2f45174a021c2009437135f03e30d206eb3915be30d4003c87f01ca0055305043fa02ce12ceccc9ed54e02182100f8a7ea5ba1718191a0168546331db3c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d0c7051b00b27170274713506ac8553082107362d09c5005cb1f13cb3f01fa02cecec9264314450010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb0000a6206ef2d0807083067004c8018210d53276db58cb1fcb3fc91034413010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb0004fc8f6f31d33ffa00fa40d72c01916d93fa4001e201f40431fa00f8416f245b8142ac3228c705f2f48166805385bef2f45174a152842adb3c5c705920f90022f9005ad76501d76582020134c8cb17cb0fcb0fcbffcbff71f90400c87401cb0212ca07cbffc9d050767080407f2b4813507dc8e0018210595f07bcbae3025f051b1c1d20001ef82ac87001ca0055215023cececcc900f255508210178d45195007cb1f15cb3f5003fa02ce01206e9430cf84809201cee201fa02cec910561058103441301810464515504403c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb004003c87f01ca0055305043fa02ce12ceccc9ed5402fed33ffa00d72c01916d93fa4001e231f8416f245b8142ac3225c705f2f48166805352bef2f45141a17080405414357f08c8553082107bdd97de5005cb1f13cb3f01fa02ce01206e9430cf84809201cee2c926044313506610246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf818ae2f400c9011e1f001a58cf8680cf8480f400f400cf81002cfb004003c87f01ca0055305043fa02ce12ceccc9ed540006f2c08201ca556082100f8a7ea55008cb1f16cb3f5004fa0212ce01206e9430cf84809201cee2f40001fa02cec944304cb010246d50436d03c8cf8580ca00cf8440ce01fa028069cf40025c6e016eb0935bcf819d58cf8680cf8480f400f400cf81e2f400c901fb00551522003cc87f01ca0055705078ce15cc13cececb3fca0001c8f40012f400cdc9ed5401faba8e3a313403fa4030f8416f245b8200e53b3224c705f2f410571046443512c87f01ca0055705078ce15cc13cececb3fca0001c8f40012f400cdc9ed54e021812002ba8e366c21d20030f8416f245b8200e53b3224c705f2f410575514c87f01ca0055705078ce15cc13cececb3fca0001c8f40012f400cdc9ed54e0012400d88210946a98b6ba8e5dd33f30c8018210aff90f5758cb1fcb3fc91068105710461035443012f84270705003804201503304c8cf8580ca00cf8440ce01fa02806acf40f400c901fb00c87f01ca0055705078ce15cc13cececb3fca0001c8f40012f400cdc9ed54e05f09f2c08275a728e5');
    const builder = beginCell();
    builder.storeUint(0, 1);
    initXeraVesting_init_args({ $$type: 'XeraVesting_init_args', minter, jettonWalletCode, distributor, admin, vestingDurationSeconds })(builder);
    const __data = builder.endCell();
    return { code: __code, data: __data };
}

export const XeraVesting_errors = {
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
    7445: { message: "XeraVesting: deposits paused" },
    11354: { message: "XeraVesting: notification not from our own jetton wallet" },
    16591: { message: "XeraVesting: referenceId already deposited" },
    17068: { message: "XeraJettonWallet: not owner" },
    26240: { message: "XeraJettonWallet: insufficient balance" },
    29707: { message: "XeraJettonWallet: unauthorized credit" },
    34116: { message: "XeraVesting: nothing to release" },
    42316: { message: "XeraVesting: credit not from the authorized distributor" },
    58683: { message: "XeraVesting: not admin" },
    63506: { message: "XeraVesting: unknown referenceId" },
} as const

export const XeraVesting_errors_backward = {
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
    "XeraVesting: deposits paused": 7445,
    "XeraVesting: notification not from our own jetton wallet": 11354,
    "XeraVesting: referenceId already deposited": 16591,
    "XeraJettonWallet: not owner": 17068,
    "XeraJettonWallet: insufficient balance": 26240,
    "XeraJettonWallet: unauthorized credit": 29707,
    "XeraVesting: nothing to release": 34116,
    "XeraVesting: credit not from the authorized distributor": 42316,
    "XeraVesting: not admin": 58683,
    "XeraVesting: unknown referenceId": 63506,
} as const

const XeraVesting_types: ABIType[] = [
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
    {"name":"Tranche","header":null,"fields":[{"name":"owner","type":{"kind":"simple","type":"address","optional":false}},{"name":"amount","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"released","type":{"kind":"simple","type":"uint","optional":false,"format":"coins"}},{"name":"start","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"duration","type":{"kind":"simple","type":"uint","optional":false,"format":64}}]},
    {"name":"ReleaseOne","header":128116498,"fields":[{"name":"referenceId","type":{"kind":"simple","type":"uint","optional":false,"format":256}}]},
    {"name":"XeraVesting$Data","header":null,"fields":[{"name":"minter","type":{"kind":"simple","type":"address","optional":false}},{"name":"jettonWalletCode","type":{"kind":"simple","type":"cell","optional":false}},{"name":"distributor","type":{"kind":"simple","type":"address","optional":false}},{"name":"admin","type":{"kind":"simple","type":"address","optional":false}},{"name":"vestingDuration","type":{"kind":"simple","type":"uint","optional":false,"format":64}},{"name":"paused","type":{"kind":"simple","type":"bool","optional":false}},{"name":"tranches","type":{"kind":"dict","key":"int","value":"Tranche","valueFormat":"ref"}},{"name":"userLockedTotal","type":{"kind":"dict","key":"address","value":"int"}}]},
]

const XeraVesting_opcodes = {
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
    "ReleaseOne": 128116498,
}

const XeraVesting_getters: ABIGetter[] = [
    {"name":"releasable","methodId":104853,"arguments":[{"name":"referenceId","type":{"kind":"simple","type":"int","optional":false,"format":257}}],"returnType":{"kind":"simple","type":"int","optional":false,"format":257}},
    {"name":"locked_remaining","methodId":71936,"arguments":[{"name":"owner","type":{"kind":"simple","type":"address","optional":false}}],"returnType":{"kind":"simple","type":"int","optional":false,"format":257}},
    {"name":"tranche_of","methodId":89828,"arguments":[{"name":"referenceId","type":{"kind":"simple","type":"int","optional":false,"format":257}}],"returnType":{"kind":"simple","type":"Tranche","optional":true}},
]

export const XeraVesting_getterMapping: { [key: string]: string } = {
    'releasable': 'getReleasable',
    'locked_remaining': 'getLockedRemaining',
    'tranche_of': 'getTrancheOf',
}

const XeraVesting_receivers: ABIReceiver[] = [
    {"receiver":"internal","message":{"kind":"typed","type":"JettonTransferNotification"}},
    {"receiver":"internal","message":{"kind":"typed","type":"ReleaseOne"}},
    {"receiver":"internal","message":{"kind":"typed","type":"SetDistributor"}},
    {"receiver":"internal","message":{"kind":"typed","type":"SetPaused"}},
    {"receiver":"internal","message":{"kind":"typed","type":"Deploy"}},
]


export class XeraVesting implements Contract {
    
    public static readonly storageReserve = 0n;
    public static readonly errors = XeraVesting_errors_backward;
    public static readonly opcodes = XeraVesting_opcodes;
    
    static async init(minter: Address, jettonWalletCode: Cell, distributor: Address, admin: Address, vestingDurationSeconds: bigint) {
        return await XeraVesting_init(minter, jettonWalletCode, distributor, admin, vestingDurationSeconds);
    }
    
    static async fromInit(minter: Address, jettonWalletCode: Cell, distributor: Address, admin: Address, vestingDurationSeconds: bigint) {
        const __gen_init = await XeraVesting_init(minter, jettonWalletCode, distributor, admin, vestingDurationSeconds);
        const address = contractAddress(0, __gen_init);
        return new XeraVesting(address, __gen_init);
    }
    
    static fromAddress(address: Address) {
        return new XeraVesting(address);
    }
    
    readonly address: Address; 
    readonly init?: { code: Cell, data: Cell };
    readonly abi: ContractABI = {
        types:  XeraVesting_types,
        getters: XeraVesting_getters,
        receivers: XeraVesting_receivers,
        errors: XeraVesting_errors,
    };
    
    constructor(address: Address, init?: { code: Cell, data: Cell }) {
        this.address = address;
        this.init = init;
    }
    
    async send(provider: ContractProvider, via: Sender, args: { value: bigint, bounce?: boolean| null | undefined }, message: JettonTransferNotification | ReleaseOne | SetDistributor | SetPaused | Deploy) {
        
        let body: Cell | null = null;
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'JettonTransferNotification') {
            body = beginCell().store(storeJettonTransferNotification(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'ReleaseOne') {
            body = beginCell().store(storeReleaseOne(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'SetDistributor') {
            body = beginCell().store(storeSetDistributor(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'SetPaused') {
            body = beginCell().store(storeSetPaused(message)).endCell();
        }
        if (message && typeof message === 'object' && !(message instanceof Slice) && message.$$type === 'Deploy') {
            body = beginCell().store(storeDeploy(message)).endCell();
        }
        if (body === null) { throw new Error('Invalid message type'); }
        
        await provider.internal(via, { ...args, body: body });
        
    }
    
    async getReleasable(provider: ContractProvider, referenceId: bigint) {
        const builder = new TupleBuilder();
        builder.writeNumber(referenceId);
        const source = (await provider.get('releasable', builder.build())).stack;
        const result = source.readBigNumber();
        return result;
    }
    
    async getLockedRemaining(provider: ContractProvider, owner: Address) {
        const builder = new TupleBuilder();
        builder.writeAddress(owner);
        const source = (await provider.get('locked_remaining', builder.build())).stack;
        const result = source.readBigNumber();
        return result;
    }
    
    async getTrancheOf(provider: ContractProvider, referenceId: bigint) {
        const builder = new TupleBuilder();
        builder.writeNumber(referenceId);
        const source = (await provider.get('tranche_of', builder.build())).stack;
        const result_p = source.readTupleOpt();
        const result = result_p ? loadTupleTranche(result_p) : null;
        return result;
    }
    
}